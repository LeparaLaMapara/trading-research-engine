"""The E10 screen on a synthetic market: plumbing, point-in-time rules and verdict logic.
No real prices are read here (the real run is pre-registered and happens once)."""
import sqlite3

import numpy as np
import pandas as pd
import pytest

from learning import families as F
from learning import screen as S


def test_rules_are_point_in_time():
    close = pd.Series(np.r_[np.full(30, 100.0), np.full(30, 110.0)])
    pos = F.tsmom(close, 5)
    # the jump happens between bar 29 and 30; momentum may only turn on from bar 31
    assert pos.iloc[30] == 0 and pos.iloc[31] == 1
    assert (F.reversal(close, 5) == -pos).all()


def test_turn_of_month_uses_the_calendar_only():
    days = pd.bdate_range("2026-09-24", "2026-10-07")
    on = F.turn_month(days)
    assert on[pd.Timestamp("2026-09-30")] == 1           # last weekday of September
    assert on[pd.Timestamp("2026-10-01")] == 1 and on[pd.Timestamp("2026-10-05")] == 1
    assert on[pd.Timestamp("2026-10-06")] == 0 and on[pd.Timestamp("2026-09-29")] == 0


def test_time_of_day_direction_depends_on_the_dollar_side():
    idx = pd.date_range("2026-10-01", periods=24, freq="h")
    assert F.time_of_day(idx, True, 13, 21).sum() == 8
    assert F.time_of_day(idx, False, 13, 21).sum() == -8


def test_xs_momentum_is_long_top_short_bottom():
    idx = pd.bdate_range("2025-01-01", periods=80)
    closes = pd.DataFrame({c: 100 * (1 + g) ** np.arange(80) for c, g in
                           zip("ABCDEFG", [0.01, 0.005, 0.002, 0.0, -0.002, -0.005, -0.01])}, index=idx)
    w = F.xs_momentum(closes, lookback=21, top=3, rebalance_every=21)
    last = w.iloc[-1]
    assert last["A"] == 1 and last["G"] == -1 and last["D"] == 0
    assert w.sum(axis=1).abs().max() == 0


@pytest.fixture
def market(tmp_path, monkeypatch):
    db = tmp_path / "market.db"
    rng = np.random.default_rng(0)
    days = pd.bdate_range("2014-06-01", "2026-09-10")
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE bars (symbol, period, ts_utc, open, high, low, close, volume)")
        for sym, drift in (("EURUSD", 0.0), ("USDJPY", 0.0), ("US500", 0.0004), ("GBPUSD", 0.0),
                           ("AUDUSD", 0.0), ("USDCAD", 0.0), ("USDCHF", 0.0), ("NZDUSD", 0.0)):
            px = 100 * np.exp(np.cumsum(rng.normal(drift, 0.008, len(days))))
            ts = [(d - pd.Timedelta(hours=3)).timestamp() for d in days]
            c.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)",
                          [(sym, "D1", float(t), p, p, p, p, 0) for t, p in zip(ts, px)])
        hrs = pd.date_range("2024-01-01", "2025-06-01", freq="h")
        hrs = hrs[hrs.dayofweek < 5]
        ph = 1.1 * np.exp(np.cumsum(rng.normal(0, 0.0008, len(hrs))))
        c.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)",
                      [("EURUSD", "H1", float(t.timestamp()), p, p, p, p, 0) for t, p in zip(hrs, ph)])
    monkeypatch.setenv("MARKET_DB", str(db))
    monkeypatch.setattr(S, "MIN_D1_BARS", 100)
    swaps = {s: {"pipPosition": 4, "swapLong": -0.5, "swapShort": -0.5, "swapCalculationType": 0}
             for s in ("EURUSD", "USDJPY", "US500", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD")}
    monkeypatch.setattr(S.FIN, "load", lambda *_: swaps)
    monkeypatch.setattr(S, "instrument_costs", lambda sym, ref, sw: {"cost_rt": 0.0002, "fee": 0.01})
    r = pd.DataFrame({"USD": 3.0, "EUR": 1.0, "JPY": 0.1, "GBP": 4.0, "AUD": 3.5, "CAD": 2.5,
                      "CHF": 0.5, "NZD": 4.5},
                     index=pd.date_range("2013-01-01", "2026-09-15", freq="D"))
    monkeypatch.setattr(S, "load_rates", lambda: r)


def test_screen_counts_every_trial_and_gives_each_a_verdict(market):
    res = S.screen(record=False, n_prior=300, log=lambda *_: None)
    assert res["instruments"] == 8
    assert res["n_after"] == 300 + res["trials"]
    fams = {t["family"] for t in res["trials_detail"]}
    assert fams == {"tsmom", "reversal", "turn_month", "carry", "time_of_day", "xs_mom"}
    assert all(t["verdict"] in ("IN", "OUT", "UNDECIDED") for t in res["trials_detail"])
    # carry only where both currencies have rates: the 7 FX pairs, not the index
    assert not any(t["symbol"] == "US500" for t in res["trials_detail"] if t["family"] == "carry")
    assert sum(res["verdicts"].values()) == res["trials"]
    for c in res["candidates"]:
        assert c["t"] >= 2.0


def test_noise_is_not_let_in(market):
    res = S.screen(record=False, n_prior=300, log=lambda *_: None)
    # random-walk prices: nothing should clear every screen check
    ins = [t for t in res["trials_detail"] if t["verdict"] == "IN" and t["symbol"] != "US500"]
    assert len(ins) <= 1
