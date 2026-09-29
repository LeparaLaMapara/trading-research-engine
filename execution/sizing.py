"""How big should the position be? Plain arithmetic, and allowed to answer "none".

Nothing in this project sized a position until now. The research half decided WHAT, and the
path from there to a live order was a print statement. This is the first half of that gap.

The rule, in one line: risk a fixed fraction of equity, and let the stop distance decide the
size. Not the other way round.

    risk_amount   = equity * risk_fraction
    size          = risk_amount / (stop_distance * value_per_unit_move)

Then reality intrudes, in this order, and each step can shrink the answer to nothing:

  1. The broker's minimum position. Below it there is no trade, only a refusal.
  2. The volume step. Sizes are rounded DOWN, never up: rounding up quietly exceeds the risk
     limit that the whole calculation exists to respect.
  3. Margin. The broker is asked what the position costs; a size that cannot be funded is not
     a size.
  4. Free-margin headroom after the stop is hit, so a normal loss does not trigger a
     forced close.

**The most important behaviour here is REFUSAL.** On a small account the minimum tradeable
size frequently risks more than the limit allows, and the correct answer is no trade rather
than a smaller limit. At R540 with 1:50 leverage, one minimum EURUSD position risks about
10% of the account: this module says no, and that is the module working.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolSpec:
    """The broker's constraints for one instrument. All volumes in cTrader units."""
    name: str
    min_volume: int
    step_volume: int
    max_volume: int
    lot_size: int          # units per lot, as the broker reports it
    pip_size: float        # price move of one pip, e.g. 0.0001
    digits: int = 5
    #: Account currency (USD) per one unit of the QUOTE currency. 1.0 for USD-quoted symbols.
    #: Without it a yen pip was counted as a dollar pip, and EURJPY "risked" 2,273% of the
    #: account (2026-09-29). None means the rate is unknown, and sizing then refuses.
    quote_to_account: float | None = 1.0


@dataclass(frozen=True)
class Sizing:
    """The answer, including the case where the answer is no."""
    allowed: bool
    volume: int                  # broker units; 0 when not allowed
    lots: float
    risk_amount: float           # what a stop-out actually costs, in account currency
    risk_fraction_actual: float  # what fraction of equity that really is
    margin_required: float | None
    reason: str

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "volume": self.volume, "lots": self.lots,
                "risk_amount": round(self.risk_amount, 4),
                "risk_fraction_actual": round(self.risk_fraction_actual, 5),
                "margin_required": self.margin_required, "reason": self.reason}


def value_per_pip(spec: SymbolSpec, volume: int) -> float:
    """Account-currency value of a one-pip move, for this volume.

    cTrader volumes are in hundredths of a base-currency unit, so units = volume / 100.
    A pip moves the price in the QUOTE currency, so the result is converted with
    `spec.quote_to_account`.
    """
    units = volume / 100.0
    return units * spec.pip_size * (spec.quote_to_account or 0.0)


def size_position(equity: float, risk_fraction: float, stop_pips: float, spec: SymbolSpec,
                  margin_per_min_volume: float | None = None,
                  free_margin_buffer: float = 1.5,
                  max_margin_fraction: float | None = None) -> Sizing:
    """Largest position that respects the risk limit, or a refusal explaining why not.

    `margin_per_min_volume` should come from the broker (ProtoOAExpectedMarginReq), not from
    an assumed leverage. Leverage on this account was inferred as 1:100 and was actually
    1:50, which doubled the real margin; asking removes that whole class of error.

    When the risk-sized position needs more margin than allowed (`max_margin_fraction` of
    equity, or not enough free margin to absorb the stop), the size steps DOWN toward the
    broker minimum before giving up. Until 2026-09-29 it gave up at once, so EURGBP was
    refused at 0.02 lots when 0.01 fitted.
    """
    if equity <= 0:
        return Sizing(False, 0, 0.0, 0.0, 0.0, None, "no equity")
    if stop_pips <= 0:
        return Sizing(False, 0, 0.0, 0.0, 0.0, None,
                      "no stop distance: a position without a stop cannot be sized")
    if not 0 < risk_fraction < 1:
        return Sizing(False, 0, 0.0, 0.0, 0.0, None,
                      f"risk fraction {risk_fraction} is not between 0 and 1")
    if spec.quote_to_account is None or spec.quote_to_account <= 0:
        return Sizing(False, 0, 0.0, 0.0, 0.0, None,
                      "no conversion rate from the quote currency to the account currency: "
                      "the risk cannot be stated, so no trade")

    risk_amount = equity * risk_fraction
    # Value of the full stop distance, per unit of volume.
    loss_per_volume = value_per_pip(spec, 1) * stop_pips
    if loss_per_volume <= 0:
        return Sizing(False, 0, 0.0, 0.0, 0.0, None, "degenerate pip value")

    raw = risk_amount / loss_per_volume
    # Round DOWN to the step. Rounding up would exceed the limit this function exists to hold.
    stepped = int(raw // spec.step_volume) * spec.step_volume

    if stepped < spec.min_volume:
        min_loss = value_per_pip(spec, spec.min_volume) * stop_pips
        return Sizing(
            False, 0, 0.0, min_loss, min_loss / equity, None,
            f"the smallest position the broker allows ({spec.min_volume / spec.lot_size:g} "
            f"lots) would risk {min_loss / equity * 100:.1f}% of the account, above the "
            f"{risk_fraction * 100:.1f}% limit. No trade.")

    volume = min(stepped, spec.max_volume)
    if margin_per_min_volume is None:
        actual_loss = value_per_pip(spec, volume) * stop_pips
        return Sizing(True, volume, volume / spec.lot_size, actual_loss, actual_loss / equity,
                      None, "ok")

    # Step down until the margin fits. Every size tried is at or below the risk-sized one,
    # so stepping down can only lower the risk, never raise it.
    why = ""
    while volume >= spec.min_volume:
        actual_loss = value_per_pip(spec, volume) * stop_pips
        margin = margin_per_min_volume * (volume / spec.min_volume)
        if margin > equity:
            why = f"margin {margin:.2f} exceeds equity {equity:.2f}"
        elif max_margin_fraction is not None and margin > equity * max_margin_fraction:
            why = (f"margin {margin:.2f} is above {max_margin_fraction * 100:.0f}% of "
                   f"equity {equity:.2f}")
        elif equity - margin < actual_loss * free_margin_buffer:
            # Room to take the loss without the broker force-closing the position first.
            why = (f"margin {margin:.2f} leaves {equity - margin:.2f} free, too little "
                   f"to absorb a {actual_loss:.2f} stop without a forced close")
        else:
            break
        volume -= spec.step_volume
    else:
        return Sizing(False, 0, 0.0, actual_loss, actual_loss / equity, margin,
                      f"{why}, even at the broker minimum")

    return Sizing(True, volume, volume / spec.lot_size, actual_loss, actual_loss / equity,
                  margin, "ok")


def stop_and_target(entry: float, side: str, stop_pips: float, spec: SymbolSpec,
                    reward_ratio: float = 1.5) -> tuple[float, float]:
    """Absolute stop-loss and take-profit prices for an entry.

    A position is never opened without both. The backtest assumes a target position can be
    held; live, an unmanaged position is an open-ended bet on the connection staying up.
    """
    dist = stop_pips * spec.pip_size
    if side.upper() == "BUY":
        return round(entry - dist, spec.digits), round(entry + dist * reward_ratio, spec.digits)
    return round(entry + dist, spec.digits), round(entry - dist * reward_ratio, spec.digits)
