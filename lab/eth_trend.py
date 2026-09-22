"""E05: Ethereum 20-day trend (docs/programme/E05-eth-trend-live-prereg.md).

`signal` is the ONE function both the history test and the live trader call, so the rule that
trades is the rule that was tested.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LOOKBACK = 20
STOP_SIGMAS, REWARD_RATIO = 2.0, 1.5
EWMA_SPAN = 36
LONG_FINANCING = 0.20            # a year, charged per day held long; shorts pay 0 here


def signal(closes: pd.Series) -> int:
    """+1 long, -1 short, 0 no view. `closes` are COMPLETED daily closes, oldest first."""
    c = closes.dropna()
    if len(c) < LOOKBACK + 1:
        return 0
    r = c.iloc[-1] / c.iloc[-1 - LOOKBACK] - 1.0
    return int(np.sign(r))


def ewma_sigma(closes: pd.Series, span: int = EWMA_SPAN) -> float:
    """Daily return volatility, EWMA, from completed closes only (as scripts/live_trade)."""
    r = np.diff(np.log(closes.dropna().to_numpy()))
    if len(r) == 0:
        return float("nan")
    w = 2.0 / (span + 1.0)
    var = r[0] ** 2
    for x in r[1:]:
        var = (1 - w) * var + w * x * x
    return math.sqrt(var)


def simulate(bars: pd.DataFrame, cost_rt: float, signs: pd.Series | None = None) -> pd.DataFrame:
    """Day-by-day simulation of the live rule. `bars`: ts_utc, open, high, low, close (daily).

    Each day d: decide with closes up to d-1; if flat or opposite, (close and) open at d's open
    with a stop and target from sigma known at d-1; then check d's high and low (stop first if
    both are touched); otherwise mark to d's close. `signs` replaces the signal (the null).
    Returns one row per day: position held, net return, and whether a round trip completed.
    """
    b = bars.sort_values("ts_utc").reset_index(drop=True)
    closes = b["close"]
    out = []
    pos, entry, stop, target, prev_mark = 0, None, None, None, None
    for d in range(LOOKBACK + 2, len(b)):
        hist = closes.iloc[:d]                       # completed closes before day d
        want = signal(hist) if signs is None else int(signs.iloc[d])
        o, h, lo, c = b.loc[d, ["open", "high", "low", "close"]]
        ret, trips = 0.0, 0
        if pos != 0 and want != pos:                 # flip: close at the open
            ret += pos * (o / prev_mark - 1.0) - cost_rt / 2
            pos, trips = 0, trips + 1
        if pos == 0 and want != 0:                   # open at the open, with protection
            sig = ewma_sigma(hist.iloc[-200:])
            dist = STOP_SIGMAS * sig * o
            pos, entry, prev_mark = want, o, o
            stop = o - pos * dist
            target = o + pos * dist * REWARD_RATIO
            ret -= cost_rt / 2
        if pos != 0:
            hit_stop = (lo <= stop) if pos > 0 else (h >= stop)
            hit_tgt = (h >= target) if pos > 0 else (lo <= target)
            exit_px = stop if hit_stop else (target if hit_tgt else None)
            mark = exit_px if exit_px is not None else c
            ret += pos * (mark / prev_mark - 1.0)
            if pos > 0:
                ret -= LONG_FINANCING / 365.0
            held = pos
            if exit_px is not None:
                ret -= cost_rt / 2
                pos, trips = 0, trips + 1
            else:
                prev_mark = c
        else:
            held = 0
        out.append((pd.Timestamp(b.loc[d, "ts_utc"], unit="s", tz="UTC"), held, ret, trips))
    return pd.DataFrame(out, columns=["date", "pos", "ret", "trips"]).set_index("date")
