"""E01's schedule: flat across the rollover, no lookahead, costs charged once per day."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import intraday as I


def _bars(days: int = 90, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=days * 24, freq="h", tz="UTC")
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, len(t))))
    secs = (t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")
    return pd.DataFrame({"ts_utc": secs, "open": px})


def test_day_table_uses_the_preregistered_hours():
    b = _bars(5)
    d = I.day_table(b)
    t = pd.to_datetime(b["ts_utc"], unit="s", utc=True)
    px = pd.Series(b["open"].to_numpy(), index=t)
    day = d.index[0]
    assert d.loc[day, "start"] == px[day - pd.Timedelta(hours=1)]      # 23:00 the day before
    assert d.loc[day, "entry"] == px[day + pd.Timedelta(hours=12)]
    assert d.loc[day, "exit"] == px[day + pd.Timedelta(hours=20)]


def test_never_holds_across_the_rollover():
    d = I.day_table(_bars())
    path = I.hourly_position_path(d, I.positions(d))
    assert not path.empty
    I.assert_flat_at_rollover(path)
    assert set(path.index.hour) == set(range(12, 20))


def test_the_rollover_guard_actually_fires():
    bad = pd.Series([1.0], index=pd.DatetimeIndex(["2024-01-02 21:00"], tz="UTC"))
    with pytest.raises(AssertionError):
        I.assert_flat_at_rollover(bad)


def test_signal_does_not_see_the_afternoon():
    """Changing prices after 12:00 must not change that day's position."""
    b = _bars(30)
    d1 = I.day_table(b)
    b2 = b.copy()
    t = pd.to_datetime(b2["ts_utc"], unit="s", utc=True)
    after = (t.dt.hour > 12) & (t.dt.hour < 23)
    b2.loc[after, "open"] *= 1.5
    d2 = I.day_table(b2)
    assert (I.positions(d1) == I.positions(d2)).all()


def test_weights_use_prior_days_only():
    d = I.day_table(_bars(120))
    w1 = I.weights(d)
    d2 = d.copy()
    d2.iloc[-1, d2.columns.get_loc("afternoon")] = 0.5        # a huge last-day move
    assert w1.iloc[-1] == I.weights(d2).iloc[-1]


def test_cost_is_charged_once_per_traded_day():
    d = I.day_table(_bars(30))
    pos = I.positions(d)
    r = I.instrument_returns(d, pos, cost_rt=0.001)
    assert np.allclose((r["gross"] - r["net"])[r["traded"]], 0.001)
    assert np.allclose((r["gross"] - r["net"])[~r["traded"]], 0.0)
