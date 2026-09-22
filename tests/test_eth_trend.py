"""E05's rule: the signal sees only the past, and the simulation charges what the live trade pays."""
from __future__ import annotations

import numpy as np
import pandas as pd

from lab import eth_trend as E


def _bars(closes, spread=0.0):
    c = np.asarray(closes, dtype=float)
    t = (pd.date_range("2024-01-01", periods=len(c), freq="D", tz="UTC")
         - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")
    return pd.DataFrame({"ts_utc": t, "open": c, "high": c + spread, "low": c - spread,
                         "close": c})


def test_signal_is_the_sign_of_the_20_day_return():
    assert E.signal(pd.Series(np.linspace(100, 120, 30))) == 1
    assert E.signal(pd.Series(np.linspace(120, 100, 30))) == -1
    assert E.signal(pd.Series([100.0] * 10)) == 0            # not enough history


def test_simulation_decides_with_yesterday_only():
    """Changing today's close must not change today's position."""
    closes = list(np.linspace(100, 130, 60))
    a = E.simulate(_bars(closes), cost_rt=0.0)
    closes2 = closes.copy()
    closes2[-1] = 1.0                                          # crash on the last day
    b = E.simulate(_bars(closes2), cost_rt=0.0)
    assert a["pos"].iloc[-1] == b["pos"].iloc[-1]


def test_steady_uptrend_is_long_and_pays_long_financing():
    s = E.simulate(_bars(np.linspace(100, 130, 80)), cost_rt=0.0)
    held = s[s["pos"] != 0]
    assert (held["pos"] == 1).all()
    # A flat day inside the trend would earn exactly minus a day of financing.
    flat = E.simulate(_bars([100.0] * 25 + [101.0] + [101.0] * 30), cost_rt=0.0)
    longs = flat[(flat["pos"] == 1)]
    assert np.isclose(longs["ret"].iloc[-1], -E.LONG_FINANCING / 365.0)


def test_stop_is_assumed_before_target_when_both_are_touched():
    closes = list(np.linspace(100, 130, 40))
    bars = _bars(closes)
    bars.loc[len(bars) - 1, ["high", "low"]] = [10_000.0, 0.01]   # touches both
    s = E.simulate(bars, cost_rt=0.0)
    assert s["ret"].iloc[-1] < 0


def test_every_open_and_every_close_pays_half_the_round_trip_cost():
    closes = list(np.linspace(100, 130, 40)) + list(np.linspace(130, 100, 40))
    free = E.simulate(_bars(closes, spread=0.5), cost_rt=0.0)
    paid = E.simulate(_bars(closes, spread=0.5), cost_rt=0.01)
    closes_n = int(free["trips"].sum())
    opens_n = closes_n + (1 if free["pos"].iloc[-1] != 0 else 0)
    assert closes_n >= 1
    assert np.isclose(free["ret"].sum() - paid["ret"].sum(), 0.005 * (opens_n + closes_n))
