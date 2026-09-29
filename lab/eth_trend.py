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


def _ewma_sigma_arr(closes: np.ndarray, span: int = EWMA_SPAN) -> float:
    r = np.diff(np.log(closes))
    if len(r) == 0:
        return float("nan")
    w = 2.0 / (span + 1.0)
    var = r[0] ** 2
    for x in r[1:]:
        var = (1 - w) * var + w * x * x
    return math.sqrt(var)


def simulate(bars: pd.DataFrame, cost_rt: float, signs: pd.Series | None = None,
             reward_ratio: float | None = REWARD_RATIO,
             long_financing: float = LONG_FINANCING, short_financing: float = 0.0,
             bars_per_year: float = 365.0) -> pd.DataFrame:
    """Day-by-day simulation of the live rule. `bars`: ts_utc, open, high, low, close (daily).

    Each day d: decide with closes up to d-1; if flat or opposite, (close and) open at d's open
    with a stop and target from sigma known at d-1; then check d's high and low (stop first if
    both are touched); otherwise mark to d's close. `signs` replaces the signal (the null).
    `reward_ratio=None` removes the profit target (E07): exits only at the stop or on a flip.
    Financing is an annual COST as a fraction of notional (negative earns), charged per bar held
    as annual / `bars_per_year`: 365 for crypto (a bar every day), 260 for weekday-only bars,
    whose weekend charges land on the Wednesday triple rollover (E08).
    Returns one row per day: position held, net return, and whether a round trip completed.
    """
    b = bars.sort_values("ts_utc").reset_index(drop=True)
    # Plain arrays: the logic is the same as a row-by-row pandas walk, about 50x faster, which
    # matters when a null runs the whole history hundreds of times (E06).
    ts = b["ts_utc"].to_numpy()
    O, H, L, C = (b[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    S = None if signs is None else np.asarray(signs, dtype=float)
    out = []
    pos, entry, stop, target, prev_mark = 0, None, None, None, None
    trade = 0
    for d in range(LOOKBACK + 2, len(b)):
        if S is None:
            r20 = C[d - 1] / C[d - 1 - LOOKBACK] - 1.0      # completed closes before day d
            want = int(np.sign(r20))
        else:
            want = int(S[d])
        o, h, lo, c = O[d], H[d], L[d], C[d]
        ret, trips = 0.0, 0
        if pos != 0 and want != pos:                 # flip: close at the open
            ret += pos * (o / prev_mark - 1.0) - cost_rt / 2
            pos, trips = 0, trips + 1
        if pos == 0 and want != 0:                   # open at the open, with protection
            sig = _ewma_sigma_arr(C[max(0, d - 200):d])
            dist = STOP_SIGMAS * sig * o
            pos, entry, prev_mark = want, o, o
            stop = o - pos * dist
            target = (o + pos * dist * reward_ratio if reward_ratio is not None
                      else pos * float("inf"))
            trade += 1
            ret -= cost_rt / 2
        if pos != 0:
            hit_stop = (lo <= stop) if pos > 0 else (h >= stop)
            hit_tgt = (h >= target) if pos > 0 else (lo <= target)
            exit_px = stop if hit_stop else (target if hit_tgt else None)
            mark = exit_px if exit_px is not None else c
            ret += pos * (mark / prev_mark - 1.0)
            ret -= (long_financing if pos > 0 else short_financing) / bars_per_year
            held = pos
            if exit_px is not None:
                ret -= cost_rt / 2
                pos, trips = 0, trips + 1
            else:
                prev_mark = c
        else:
            held = 0
        out.append((pd.Timestamp(ts[d], unit="s", tz="UTC"), held, ret, trips, trade))
    return pd.DataFrame(out, columns=["date", "pos", "ret", "trips", "trade"]).set_index("date")
