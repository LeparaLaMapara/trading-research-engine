from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research import e11_fix as E11
from research import e12_fomc as E12

SPREAD = 0.00002          # 0.2 pip


def write_quotes(tmp, sym, tf, mid: pd.Series):
    for side, sign in (("bid", -1), ("ask", 1)):
        px = mid + sign * SPREAD / 2
        df = pd.DataFrame({"timestamp": mid.index.as_unit("ms").asi8, "open": px.to_numpy(),
                           "high": px.to_numpy(), "low": px.to_numpy(), "close": px.to_numpy()})
        df.to_csv(tmp / f"{sym.lower()}-{tf}-{side}-x.csv", index=False)


def m5_mid(start, end, planted_bps: float, usd_base: bool, seed: int) -> pd.Series:
    """5-minute mids. With planted_bps > 0 the dollar rises over 02:00-08:15 ET and falls over
    11:00-16:30 ET by that many bps a leg, on top of small noise."""
    idx = pd.date_range(start, end, freq="5min", tz="UTC")
    et = idx.tz_convert("America/New_York")
    mins = et.hour * 60 + et.minute
    rng = np.random.default_rng(seed)
    step = rng.normal(0, 0.2e-4, len(idx))
    pre = (mins >= 120) & (mins < 495)               # 02:00 - 08:15
    post = (mins >= 660) & (mins < 990)              # 11:00 - 16:30
    usd_up = np.where(pre, planted_bps * 1e-4 / 75, 0) - np.where(post, planted_bps * 1e-4 / 66, 0)
    step += -usd_up if not usd_base else usd_up     # XXXUSD falls when the dollar rises
    return pd.Series(1.2 * np.exp(np.cumsum(step)), index=idx)


def make_m5(tmp, planted):
    for i, sym in enumerate(E11.INSTRUMENTS):
        write_quotes(tmp, sym, "m5", m5_mid("2020-01-01", "2020-06-30", planted,
                                            sym.startswith("USD"), seed=i))


def test_new_york_windows_follow_daylight_saving():
    g = E11.grid(pd.DatetimeIndex(["2020-01-15", "2020-07-15"]), "02:00", "02:05")
    assert pd.Timestamp(g.iloc[0, 0]).hour == 7 and pd.Timestamp(g.iloc[1, 0]).hour == 6


def test_leg_pays_spread_and_commission_on_flat_prices():
    bid, ask = np.full((1, 3), 1.0), np.full((1, 3), 1.0 + SPREAD)
    r = E11.leg(bid, ask, np.array([0]), np.array([2]), long_quote=True)
    assert r[0] == pytest.approx(np.log(1.0 / (1.0 + SPREAD)) - 0.7e-4)


def test_e11_finds_a_planted_pattern(tmp_path):
    make_m5(tmp_path, planted=4.0)
    res = E11.run(str(tmp_path), n_null=50, n_prior=100, log=lambda *_: None)
    assert res["book"]["mean_bps"] > 3
    assert res["criteria"]["1_sharpe_positive_t_ge_2"]
    assert res["criteria"]["2_beats_null_p95"]
    assert res["criteria"]["3_positive_at_1p5x_costs"]
    assert not res["criteria"]["4_positive_5_of_7_years"]     # only half a year of data
    assert res["n_total"] == 110


def test_e11_finds_nothing_in_noise(tmp_path):
    make_m5(tmp_path, planted=0.0)
    res = E11.run(str(tmp_path), n_null=50, n_prior=100, log=lambda *_: None)
    assert res["verdict"] == "FAIL"
    assert res["book"]["mean_bps"] < 0                        # costs, nothing else


# ---- E12 -----------------------------------------------------------------------------------

SWAPS = {s: {"swapLong": -0.5, "swapShort": 0.1, "swapCalculationType": 0, "pipPosition": 4,
             "swapRollover3Days": 3} for s, _ in E12.LEGS}
SWAPS["USDJPY"]["pipPosition"] = 2


def h1_mid(dates, planted_bps, buy, seed):
    idx = pd.date_range("2019-12-01", "2021-01-31", freq="1h", tz="UTC")
    rng = np.random.default_rng(seed)
    step = rng.normal(0, 3e-4, len(idx))
    ny = idx.tz_convert("America/New_York")
    for d in dates:
        d = pd.Timestamp(d)
        start = (d - pd.offsets.BDay(1)).normalize() + pd.Timedelta(hours=16)
        sel = (ny >= start.tz_localize("America/New_York")) & \
              (ny < (d.normalize() + pd.Timedelta(hours=16)).tz_localize("America/New_York"))
        step[sel] += (planted_bps * 1e-4 / sel.sum()) * (1 if buy else -1)
    base = 110.0 if not buy else 1.2
    return pd.Series(base * np.exp(np.cumsum(step)), index=idx)


DATES = [str(d.date()) for d in pd.date_range("2020-01-08", "2020-12-30", freq="W-WED")]


def make_h1(tmp, planted):
    for i, (sym, buy) in enumerate(E12.LEGS):
        write_quotes(tmp, sym, "h1", h1_mid(DATES, planted, buy, seed=i))


def test_triple_night_is_wednesday_only():
    assert E12.nights(pd.Timestamp("2026-10-28"), {"swapRollover3Days": 3}) == 3     # Wednesday
    assert E12.nights(pd.Timestamp("2026-10-27"), {"swapRollover3Days": 3}) == 1     # Tuesday
    assert E12.nights(pd.Timestamp("2026-10-30"), {"swapRollover3Days": 3}) == 1     # Friday


def test_e12_finds_a_planted_dollar_drop(tmp_path):
    make_h1(tmp_path, planted=40.0)
    res = E12.run(str(tmp_path), n_null=100, n_prior=100, dates=DATES, swaps=SWAPS,
                  log=lambda *_: None)
    assert res["book"]["mean_bps"] > 30
    assert res["criteria"]["1_mean_positive_t_ge_2"] and res["criteria"]["2_beats_null_p95"]
    assert res["n_total"] == 108


def test_e12_noise_does_not_pass(tmp_path):
    make_h1(tmp_path, planted=0.0)
    res = E12.run(str(tmp_path), n_null=100, n_prior=100, dates=DATES, swaps=SWAPS,
                  log=lambda *_: None)
    assert not res["criteria"]["1_mean_positive_t_ge_2"]
