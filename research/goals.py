"""Turning a person's wish into a measurable objective, and judging it honestly.

Someone types "I just want to make money". That is not actionable, and worse, it is the kind
of instruction a system can pretend to satisfy. This module turns it into four numbers, and
then answers one question with arithmetic rather than opinion: is that actually reachable?

The split matters and follows the project's rule one. An LLM may read the sentence and fill
in the blanks it implies (how much, by when, how much may be lost). It never decides whether
the goal is achievable. That verdict is computed here, in plain code, from the account's real
constraints, and it is allowed to say no.

The model, kept deliberately simple so a non-expert can follow it:

  * Each trade risks a fixed fraction f of equity. On this account f is not a choice: the
    broker's minimum position is 0.01 lots, which at a realistic stop is about 5% of R1000.
  * Wealth therefore follows a random walk in log space, drift mu per trade, spread s.
  * Reaching a target before a floor is the classic first-passage problem, which has a closed
    form. With no edge and no costs the answer depends only on how far the target and the
    floor are in log terms. Costs push the drift negative, which is why doing nothing beats
    trading badly.

Everything here is re-runnable and every constant is stated. No number in the verdict comes
from a model.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass

# --- The account's physical constraints, measured, not assumed. -----------------------
# From the broker's own symbol spec (data/telemetry.db) and the NOT_ENOUGH_MONEY rejection
# of 2026-08-11, which proved margin on the minimum position exceeds $10.
#
# LEVERAGE WAS WRONG UNTIL 2026-09-15. It had been inferred as 1:100 from that rejection,
# and everything downstream was built on it. The cTrader grant screen then showed the account
# holding the money (a second login) is 1:50, which DOUBLES the margin per trade. This is why
# `ProtoOATraderUpdatedEvent` carries `leverageInCents` and why it must be read rather than
# guessed: the whole risk table hangs off this one number.
MIN_LOT_NOTIONAL_USD = 1150.0   # 0.01 lots EURUSD = 1000 EUR at ~1.15
ACCOUNT_LEVERAGE = float(os.environ.get("ACCOUNT_LEVERAGE", "50"))
MIN_LOT_MARGIN_USD = MIN_LOT_NOTIONAL_USD / ACCOUNT_LEVERAGE
TYPICAL_STOP_PIPS = 30.0
PIP_VALUE_MIN_LOT_USD = 0.10
STOP_COST_USD = TYPICAL_STOP_PIPS * PIP_VALUE_MIN_LOT_USD          # 3.00
STOPOUT_BUFFER_USD = MIN_LOT_MARGIN_USD * 0.5                      # 5.75
# Below this the account cannot place another minimum trade, i.e. it can no longer re-bet.
REBET_FLOOR_USD = MIN_LOT_MARGIN_USD + STOP_COST_USD + STOPOUT_BUFFER_USD   # 20.25

# Round-trip cost at minimum size, from the measured cost map: EURUSD median spread 0.1 pips
# plus commission. Deliberately conservative.
COST_PER_TRADE_USD = 0.06
DEFAULT_TRADES_PER_YEAR = 250
DEFAULT_ZAR_PER_USD = 18.0

# Reference points so a verdict can be put in context rather than left as a bare number.
# Sources: Bailey & Lopez de Prado E[max SR] at N=1000 with sigma 0.5; published gross Sharpe
# of the best-known quantitative funds.
NOISE_SHARPE_AT_1000_TRIALS = 1.63
WORLD_CLASS_SHARPE = 2.5
# Above this chance of being unable to trade again, a goal is refused however small the
# required skill looks. Risking more per trade always flatters the required Sharpe.
MAX_ACCEPTABLE_RUIN = 0.35


@dataclass
class GoalSpec:
    """A wish, specialised into something that can be measured."""
    author: str
    raw_text: str
    target_zar: float
    horizon_days: int
    risk_zar: float
    start_zar: float


@dataclass
class Feasibility:
    """The deterministic verdict. Every field is computed, none is asserted."""
    feasible: bool
    required_return_pct: float
    required_annual_return_pct: float
    achievable_annual_vol_pct: float
    required_sharpe: float
    risk_per_trade_pct: float
    prob_reach_target_no_edge: float
    prob_hit_floor_no_edge: float
    floor_zar: float
    verdict_plain: str
    context_plain: str

    def to_dict(self) -> dict:
        return asdict(self)


def rebet_floor_zar(zar_per_usd: float = DEFAULT_ZAR_PER_USD) -> float:
    """The equity below which the account can no longer place a trade at all."""
    return REBET_FLOOR_USD * zar_per_usd


def risk_per_trade_fraction(equity_zar: float, zar_per_usd: float = DEFAULT_ZAR_PER_USD) -> float:
    """What fraction of equity one minimum-size trade puts at risk.

    This is forced by the broker, not chosen. There is no position smaller than 0.01 lots, so
    on a small account the risk per trade is whatever that works out to be.
    """
    equity_usd = max(equity_zar / zar_per_usd, 1e-9)
    return min(STOP_COST_USD / equity_usd, 1.0)


def horizon_outcome(start: float, target: float, floor: float, f: float,
                    n_trades: int, cost_frac: float, seed: int = 7,
                    paths: int = 20000) -> tuple[float, float]:
    """P(reach target), P(fall to floor) WITHIN the horizon, with no edge.

    Why a simulation rather than the closed form. The first-passage formula answers "does it
    hit the floor *ever*", and with costs dragging the drift negative the honest answer to
    that is eventually yes, for any stake. Over one year that is not the question anyone is
    asking, and reporting it made a well-funded account look doomed (94% ruin on R5,400) while
    a tiny one looked fine. This bounds the walk by the trades that actually fit in the
    horizon.

    The model: each trade wins or loses f of equity on a coin flip, minus costs. No edge is
    assumed, deliberately, because none has been demonstrated. Seeded, so it is re-runnable
    and gives the same answer every time.
    """
    import numpy as np
    if start <= floor or target <= start or n_trades <= 0 or f <= 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    up, dn = math.log(target / start), math.log(start / floor)
    # Log return per trade, win or lose, with the cost applied either way.
    win, loss = math.log(1 + f) - cost_frac, math.log(1 - f) - cost_frac

    # Simulated in CHUNKS rather than as one array. The whole grid at 20,000 paths is a
    # single 38MB float64 allocation, which failed outright on a machine that was busy with
    # other work. A number the family reads off a dashboard must not depend on there being
    # tens of megabytes of contiguous memory free, and float32 is far more precision than a
    # barrier-crossing count needs.
    chunk = 2000
    reached_n = ruined_n = 0
    done = 0
    while done < paths:
        m = min(chunk, paths - done)
        steps = np.where(rng.random((m, n_trades), dtype=np.float32) < 0.5,
                         np.float32(win), np.float32(loss))
        walk = np.cumsum(steps, axis=1, dtype=np.float32)
        got_up = (walk >= up).any(axis=1)
        got_dn = (walk <= -dn).any(axis=1)
        # Whichever barrier is touched first decides the path.
        hit_up = np.argmax(walk >= up, axis=1)
        hit_dn = np.argmax(walk <= -dn, axis=1)
        reached_n += int((got_up & (~got_dn | (hit_up < hit_dn))).sum())
        ruined_n += int((got_dn & (~got_up | (hit_dn < hit_up))).sum())
        done += m
        del steps, walk
    return (reached_n / paths, ruined_n / paths)


def _first_passage_up(a: float, b: float, mu: float, s2: float) -> float:
    """P(log-wealth rises by `a` before falling by `b`), drift mu, variance s2 per step.

    Driftless case reduces to b / (a + b), the familiar gambler's ruin result: the nearer
    barrier in log space is the likelier one.
    """
    if a <= 0:
        return 1.0
    if b <= 0:
        return 0.0
    if abs(mu) < 1e-12 or s2 <= 0:
        return b / (a + b)
    k = 2.0 * mu / s2
    try:
        num = 1.0 - math.exp(-k * b)
        den = 1.0 - math.exp(-k * (a + b))
        if abs(den) < 1e-15:
            return b / (a + b)
        return max(0.0, min(1.0, num / den))
    except OverflowError:  # pragma: no cover - extreme drift
        return 1.0 if mu > 0 else 0.0


def assess(spec: GoalSpec, trades_per_year: int = DEFAULT_TRADES_PER_YEAR,
           zar_per_usd: float = DEFAULT_ZAR_PER_USD) -> Feasibility:
    """Judge a specialised goal against the account's real constraints."""
    start = max(float(spec.start_zar), 1e-9)
    target = float(spec.target_zar)
    days = max(int(spec.horizon_days), 1)

    required_return = (target / start) - 1.0
    years = days / 365.0
    # Compound, not simple: doubling in three months is not "four times doubling in a year".
    required_annual = (target / start) ** (1.0 / years) - 1.0 if years > 0 else float("inf")

    f = risk_per_trade_fraction(start, zar_per_usd)
    n_trades = max(trades_per_year * years, 1.0)
    # Volatility a strategy can actually generate at this forced position size. Risking f per
    # trade over N trades gives roughly f * sqrt(N) of annual volatility.
    achievable_vol = f * math.sqrt(trades_per_year)
    required_sharpe = required_annual / achievable_vol if achievable_vol > 0 else float("inf")

    floor = rebet_floor_zar(zar_per_usd)
    a = math.log(target / start) if target > start else 0.0
    b = math.log(start / floor) if start > floor else 0.0
    # Costs alone give a negative drift: this is why a system with no edge loses slowly
    # instead of breaking even.
    cost_frac = COST_PER_TRADE_USD / max(start / zar_per_usd, 1e-9)
    p_up, p_ruin = horizon_outcome(start, target, floor, f, int(n_trades), cost_frac)

    # Feasible means BOTH: the skill required is humanly achievable, AND the attempt does not
    # probably destroy the account first. Without the second clause the model rewarded raising
    # risk per trade, because that lowers the required Sharpe while raising ruin - exactly the
    # behaviour that empties a small account.
    feasible = (required_sharpe <= WORLD_CLASS_SHARPE and target > start and start > floor
                and p_ruin <= MAX_ACCEPTABLE_RUIN)

    rands = lambda v: f"R{v:,.0f}"  # noqa: E731 - local formatting shorthand
    if target <= start:
        verdict = (f"That goal does not ask for growth: it starts at {rands(start)} and asks "
                   f"for {rands(target)}.")
    elif start <= floor:
        # Two different thresholds, and conflating them is misleading. Opening the smallest
        # trade needs only the margin. Surviving the stop on it without the broker force
        # closing you needs margin plus room to lose. Say which one is binding.
        margin_zar = MIN_LOT_MARGIN_USD * zar_per_usd
        if start > margin_zar:
            verdict = (f"The account is at {rands(start)}. One smallest-size trade would tie "
                       f"up {rands(margin_zar)} of that as margin, leaving too little to "
                       f"absorb a normal loss without the broker closing the position for "
                       f"you. It needs about {rands(floor)} to trade with any room to "
                       f"breathe.")
        else:
            verdict = (f"The account is at {rands(start)}, below the {rands(margin_zar)} "
                       f"needed just to open the smallest possible trade. Nothing can be "
                       f"attempted until it is funded above that.")
    elif feasible:
        verdict = (f"To turn {rands(start)} into {rands(target)} in {days} days the engine "
                   f"needs to earn {required_return*100:.0f}%, which works out to "
                   f"{required_annual*100:.0f}% a year. At the smallest trade this account "
                   f"can place, that needs skill worth a Sharpe of about "
                   f"{required_sharpe:.2f}. That is demanding but not impossible.")
    elif required_sharpe <= WORLD_CLASS_SHARPE and p_ruin > MAX_ACCEPTABLE_RUIN:
        verdict = (f"Reaching {rands(target)} from {rands(start)} in {days} days is possible "
                   f"on skill alone, but not safely: each trade has to risk "
                   f"{f*100:.0f}% of the account, and that gives a {p_ruin*100:.0f}% chance "
                   f"of dropping below {rands(floor)} and not being able to trade at all "
                   f"before it ever gets there. More money in, or a longer deadline, fixes "
                   f"this. Risking more does not.")
    else:
        verdict = (f"To turn {rands(start)} into {rands(target)} in {days} days the engine "
                   f"would need to earn {required_return*100:.0f}%, which works out to "
                   f"{required_annual*100:,.0f}% a year. At the smallest trade this account "
                   f"can place, that needs skill worth a Sharpe of about "
                   f"{required_sharpe:,.1f}. The best quantitative funds in history run "
                   f"about {WORLD_CLASS_SHARPE}. So no, not on this timeline. Give it longer "
                   f"or put in more, and the same goal becomes reachable.")

    context = (f"Every trade this account can place risks about {f*100:.1f}% of it, because "
               f"the broker has no smaller position. ")
    if target > start and start > floor:
        # Only meaningful when there is actually a target above the current balance and a
        # floor below it. Otherwise the first-passage number is arithmetic about nothing.
        context += (f"With no real edge, the chance of reaching {rands(target)} before "
                    f"dropping to the {rands(floor)} floor is about {p_up*100:.0f}%, and "
                    f"that is before the engine has proven it knows anything. ")
    context += (f"A Sharpe of {NOISE_SHARPE_AT_1000_TRIALS} can be produced by pure luck "
                f"after a thousand attempts, which is why the engine refuses to trade on a "
                f"good-looking backtest alone.")

    return Feasibility(
        feasible=feasible,
        required_return_pct=round(required_return * 100, 2),
        required_annual_return_pct=round(required_annual * 100, 2),
        achievable_annual_vol_pct=round(achievable_vol * 100, 2),
        required_sharpe=round(required_sharpe, 3),
        risk_per_trade_pct=round(f * 100, 2),
        prob_reach_target_no_edge=round(p_up, 4),
        prob_hit_floor_no_edge=round(p_ruin, 4),
        floor_zar=round(floor, 2),
        verdict_plain=verdict,
        context_plain=context,
    )


def suggest_reachable(spec: GoalSpec, zar_per_usd: float = DEFAULT_ZAR_PER_USD,
                      trades_per_year: int = DEFAULT_TRADES_PER_YEAR) -> dict:
    """If the goal is out of reach, say what would put it in reach. Two honest levers only:
    more time, or more money. Neither is a promise, both are arithmetic."""
    start = max(float(spec.start_zar), 1e-9)
    target = float(spec.target_zar)
    f = risk_per_trade_fraction(start, zar_per_usd)
    vol = f * math.sqrt(trades_per_year)
    out: dict = {}
    # Below the floor, time is not the blocker and offering a deadline would mislead. The only
    # honest lever there is funding.
    below_floor = start <= rebet_floor_zar(zar_per_usd)
    if target > start and vol > 0 and not below_floor:
        # Days needed for the required annual return to fall to a world-class Sharpe.
        max_annual = WORLD_CLASS_SHARPE * vol
        if max_annual > 0:
            years = math.log(target / start) / math.log(1.0 + max_annual)
            out["days_needed_at_world_class_skill"] = int(math.ceil(years * 365))
    # Funding that would bring risk per trade down to a conventional 1% of equity.
    out["funding_for_1pct_risk_zar"] = round(STOP_COST_USD * 100 * zar_per_usd, 2)
    out["floor_zar"] = round(rebet_floor_zar(zar_per_usd), 2)
    return out


# --- the owner's own funding condition -------------------------------------------------
#
# Stated 2026-09-16: "the 5,000 I will add once I see even 1% return of what I currently
# have". That is a good condition and it is encoded here rather than left in a chat log,
# so the dashboard and the engine read the SAME number instead of each carrying a copy
# that can drift.
#
# It is deliberately a RETURN condition, not a Sharpe or a DSR. Those are the engine's
# internal bars and the owner has said he cannot check them by inspection. A realised
# percentage of a real balance is checkable by anyone.
FIRST_MILESTONE_PCT = 0.01
FIRST_MILESTONE_UNLOCK_ZAR = 5000.0


def milestone_progress(baseline_zar: float, current_zar: float,
                       pct: float = FIRST_MILESTONE_PCT,
                       unlock_zar: float = FIRST_MILESTONE_UNLOCK_ZAR) -> dict:
    """How far the account is from the owner's stated funding milestone.

    `baseline_zar` is the balance the milestone is measured FROM, which is the first
    balance ever recorded rather than the highest. Measuring from a peak would let a
    deposit or a lucky day reset the bar and quietly make it easier.

    Progress is reported CLAMPED to [0, 1] for the progress bar, alongside the unclamped
    gap, so a loss shows as 0% complete and a widened gap rather than as a negative bar
    that reads like a different kind of number.
    """
    if baseline_zar <= 0:
        return {"evaluable": False, "why_not": "no starting balance recorded",
                "baseline_zar": baseline_zar, "current_zar": current_zar,
                "target_zar": 0.0, "gap_zar": 0.0, "progress": 0.0, "reached": False,
                "pct": pct, "unlock_zar": unlock_zar}
    target = baseline_zar * (1.0 + pct)
    gained = current_zar - baseline_zar
    needed = target - baseline_zar
    return {
        "evaluable": True, "why_not": "",
        "baseline_zar": baseline_zar, "current_zar": current_zar,
        "target_zar": target, "gap_zar": target - current_zar,
        "progress": max(0.0, min(1.0, gained / needed)) if needed > 0 else 0.0,
        "reached": current_zar >= target,
        "pct": pct, "unlock_zar": unlock_zar,
    }
