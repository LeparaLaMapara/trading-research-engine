"""Delay injection: what a strategy ACTUALLY gets when it acts late.

A backtest assumes the signal formed at a bar's close is filled at that close. Nothing is
filled at the price that produced the decision. The gap between those two prices is where
edges die, and this module measures it by replaying the same decisions at a later moment.

**Resolution honesty.** A delay can only be simulated at the resolution of the data that
prices the fill. With H1 bars the finest honest fill is "the open of the first hourly bar
starting at or after the delayed moment", so a requested delay of 90 minutes becomes an
EFFECTIVE delay of 2 hours and the effective number is what gets reported. Asking this module
for 10 ms against hourly bars raises rather than silently rounding to zero: inventing
precision the dataset does not contain is the exact dishonesty this project exists to avoid.

**What is deliberately NOT modelled here.** Partial fills, rejections and queue position do
not exist for a market order on a liquid FX pair at 0.01 lots, which is what this account
sends. They matter for limit orders and for size, and they belong in the tick-level replay
(Stage D), not in a bar-level one that would have to invent them.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Bar durations in seconds, for turning a bar's start stamp into its close.
BAR_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400,
               "W1": 604800}


@dataclass
class Fill:
    """One executed decision."""
    decided_ts: float          # when the signal existed (the bar close that produced it)
    requested_delay_s: float
    effective_delay_s: float   # what the pricing data can actually represent
    filled_ts: float
    price: float
    position: float


class ResolutionError(ValueError):
    """Raised when a delay is finer than the execution data can price."""


def fills_for_delay(signals: pd.DataFrame, exec_bars: pd.DataFrame, delay_s: float,
                    exec_period: str = "H1") -> pd.DataFrame:
    """Price every decision at `delay_s` after it was made.

    signals:   columns ts_close (epoch seconds, when the decision existed) and position.
    exec_bars: columns ts_utc (bar START, epoch seconds), open, close.
    delay 0 is the conventional backtest assumption: filled at the price that made the
    decision. Every other delay is priced from `exec_bars`.
    """
    step = BAR_SECONDS[exec_period.upper()]
    if delay_s < 0:
        # A negative delay fills BEFORE the decision existed. The old guard was
        # `0 < delay_s < step`, which let it straight through.
        raise ResolutionError(f"negative delay {delay_s:g}s would fill before the decision")
    if 0 < delay_s < step:
        raise ResolutionError(
            f"a {delay_s:g}s delay cannot be priced from {exec_period} bars ({step}s). "
            f"Use finer data or drop the bucket; do not round it to zero.")

    sig = signals.sort_values("ts_close").reset_index(drop=True)
    if delay_s == 0:
        out = sig.assign(requested_delay_s=0.0, effective_delay_s=0.0,
                         filled_ts=sig["ts_close"], price=sig["decision_price"])
        return out[["ts_close", "position", "requested_delay_s", "effective_delay_s",
                    "filled_ts", "price", "decision_price"]].rename(
            columns={"ts_close": "decided_ts"})

    ex = exec_bars.sort_values("ts_utc").reset_index(drop=True)
    target = sig["ts_close"].to_numpy() + delay_s
    # The first execution bar STARTING at or after the delayed moment. Its open is the first
    # price the order could have touched; anything earlier would be trading in the past.
    idx = np.searchsorted(ex["ts_utc"].to_numpy(), target, side="left")
    ok = idx < len(ex)
    out = sig.loc[ok].copy()
    take = idx[ok]
    out["requested_delay_s"] = float(delay_s)
    out["filled_ts"] = ex["ts_utc"].to_numpy()[take]
    out["price"] = ex["open"].to_numpy()[take]
    out["effective_delay_s"] = out["filled_ts"] - out["ts_close"]
    # decision_price is CARRIED THROUGH. Dropping it here made delay_slippage_bps NULL in
    # every stored row, so "the mechanism behind any decay" was never actually measured.
    return out[["ts_close", "position", "requested_delay_s", "effective_delay_s",
                "filled_ts", "price", "decision_price"]].rename(
        columns={"ts_close": "decided_ts"})


def pnl_from_fills(fills: pd.DataFrame, cost_per_turnover: float,
                   financing_per_day: float = 0.0) -> pd.DataFrame:
    """Returns between consecutive fills, charged at the prices actually obtained.

    The whole path shifts with the delay: a late entry is also a late exit, which is why this
    cannot be approximated by subtracting a constant from the return.
    """
    f = fills.sort_values("filled_ts").reset_index(drop=True)
    price = f["price"].astype(float)
    # The LAST fill has no next price, so its return is unknowable and the row is carried with
    # a zero rather than silently dropped: pct_change().shift(-1) discarded the final bar of
    # every bucket, which is a small bias in the same direction for every strategy.
    ret = price.pct_change().shift(-1)            # return from this fill to the next
    pos = f["position"].astype(float)
    turnover = pos.diff().abs().fillna(pos.abs())
    held_days = f["filled_ts"].diff().shift(-1).fillna(0.0) / 86400.0
    gross = pos * ret
    cost = turnover * cost_per_turnover
    fin = pos.abs() * financing_per_day * held_days
    out = pd.DataFrame({"filled_ts": f["filled_ts"], "position": pos, "price": price,
                        "gross": gross.fillna(0.0), "cost": cost, "financing": fin})
    out["net"] = out["gross"] - out["cost"] - out["financing"]
    # Slippage of the delay itself: what the price did between decision and fill, signed by
    # the direction taken. Negative means the move happened before we got there.
    out["decision_price"] = f.get("decision_price", pd.Series(np.nan, index=f.index))
    out["fills_without_forward_return"] = int(ret.isna().sum())
    return out


def trade_segments(pnl: pd.DataFrame) -> list[float]:
    """Sum net return over each run of identical non-zero position: one trade, one number."""
    trades, cur, cur_pos = [], 0.0, 0.0
    for _, row in pnl.iterrows():
        if row["position"] != cur_pos:
            if cur_pos != 0.0:
                trades.append(cur)
            cur, cur_pos = 0.0, row["position"]
        if cur_pos != 0.0:
            cur += row["net"]
    if cur_pos != 0.0:
        trades.append(cur)
    return trades
