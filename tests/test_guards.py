from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from backtest.harness import CostModel, rollover_nights, run_backtest
from execution import guards
from news import calendar as cal
from strategy.base import Strategy

UTC = dt.timezone.utc


def ts(*a) -> float:
    return dt.datetime(*a, tzinfo=UTC).timestamp()


# ---- calendar -------------------------------------------------------------------------------

FEED = [
    {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00",
     "impact": "High", "forecast": "120K", "previous": "100K"},
    {"title": "German ifo", "country": "EUR", "date": "2026-11-02T05:00:00-05:00",
     "impact": "Low", "forecast": "", "previous": ""},
]


def store_for(now: float) -> dict:
    return cal.merge({"weeks": [], "events": []}, cal.parse_feed(FEED), now)


def test_feed_times_convert_with_their_offset():
    ev = cal.parse_feed(FEED)[0]
    assert ev.ts == ts(2026, 11, 6, 13, 30)          # 08:30 New York in winter = 13:30 UTC


def test_feed_without_offset_is_refused():
    with pytest.raises(ValueError):
        cal.parse_feed([{**FEED[0], "date": "2026-11-06T08:30:00"}])


def test_week_starts_sunday_new_york():
    assert cal.week_start(ts(2026, 11, 6, 13, 30)) == ts(2026, 11, 1, 4, 0)   # Sun 00:00, still EDT (DST ends 02:00)


def test_blackout_around_high_impact_only_for_its_currencies():
    st = store_for(ts(2026, 11, 2, 12))
    nfp = ts(2026, 11, 6, 13, 30)
    assert "Non-Farm" in cal.blackout("EURUSD", nfp - 20 * 60, st)
    assert "Non-Farm" in cal.blackout("ETHUSD", nfp + 25 * 60, st)
    assert cal.blackout("EURUSD", nfp - 45 * 60, st) is None
    assert cal.blackout("EURGBP", nfp, st) is None               # no USD leg
    assert cal.blackout("EURUSD", ts(2026, 11, 2, 10), st) is None  # Low impact never blocks


def test_blackout_fails_closed_without_this_weeks_calendar():
    st = store_for(ts(2026, 11, 2, 12))
    assert "calendar missing" in cal.blackout("EURUSD", ts(2026, 11, 10, 12), st)
    assert "calendar missing" in cal.blackout("EURUSD", ts(2026, 11, 3), {"weeks": [], "events": []})


def test_merge_keeps_history_and_dedupes():
    st = store_for(ts(2026, 11, 2, 12))
    st2 = cal.merge(st, cal.parse_feed(FEED), ts(2026, 11, 3, 12))
    assert len(st2["events"]) == 2 and len(st2["weeks"]) == 1


def test_unknown_symbol_has_no_silent_default():
    with pytest.raises(KeyError):
        cal.currencies_of("WEIRD1")
    assert cal.currencies_of("XAUUSD") == ("USD",)
    assert cal.currencies_of("AUDNZD") == ("AUD", "NZD")


# ---- guards ---------------------------------------------------------------------------------

def test_rollover_window_follows_new_york_daylight_saving():
    assert guards.near_rollover(ts(2026, 7, 1, 21, 0))       # summer: 17:00 NY = 21:00 UTC
    assert not guards.near_rollover(ts(2026, 7, 1, 22, 30))
    assert guards.near_rollover(ts(2026, 12, 1, 22, 30))     # winter: 17:00 NY = 22:00 UTC
    assert guards.near_rollover(ts(2026, 12, 1, 21, 31))     # 29 min before
    assert not guards.near_rollover(ts(2026, 12, 1, 21, 0))
    assert not guards.near_rollover(ts(2026, 12, 1, 15, 0))


def test_spread_gate(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"EURUSD": {"spread_pips": 0.2}}))
    assert guards.spread_reason("EURUSD", 0.3, str(p)) is None
    assert "over" in guards.spread_reason("EURUSD", 0.5, str(p))
    assert "no measured" in guards.spread_reason("GBPUSD", 0.1, str(p))


def test_entry_check_collects_every_reason(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"EURUSD": {"spread_pips": 0.2}}))
    st = store_for(ts(2026, 11, 2, 12))
    clear = ts(2026, 11, 4, 14)
    assert guards.entry_check("EURUSD", clear, 0.2, st, str(p)) == []
    r = guards.entry_check("EURUSD", ts(2026, 11, 6, 13, 40), 1.0, st, str(p))
    assert len(r) == 2 and r[0].startswith("news") and r[1].startswith("spread")
    assert guards.entry_check("NOPE99", clear, None, st, str(p))[0].startswith("news")


# ---- financing in the backtest --------------------------------------------------------------

def hourly(start: float, n: int) -> pd.Series:
    return pd.Series(np.arange(n) * 3600 + int(start))


def test_rollover_nights_hourly_fx():
    # Monday 2026-11-02 00:00 UTC, two weeks of hourly bars.
    n = rollover_nights(hourly(ts(2026, 11, 2), 24 * 14), "fx")
    assert n.sum() == 14                     # 10 weekdays, two Wednesdays count 3
    hit = n[n > 0]
    assert set(hit.unique()) == {1.0, 3.0}
    # Winter: 17:00 NY = 22:00 UTC. The charge lands on the bar that ENDS at 22:00 (opens
    # 21:00): to avoid it a rule must be flat before the rollover, not at it.
    first = int(hit.index[0])
    assert dt.datetime.fromtimestamp(ts(2026, 11, 2) + first * 3600, UTC).hour == 21


def test_rollover_nights_daily_style_counts_weekends():
    n = rollover_nights(hourly(ts(2026, 11, 2), 24 * 7), "daily")
    assert n.sum() == 7


class Always(Strategy):
    name = "always"

    def __init__(self, pos):
        self.pos = pos

    def generate_signals(self, bars):
        return pd.Series(self.pos, index=bars.index)

    def economic_rationale(self):
        return "test"


def flat_bars(n: int) -> pd.DataFrame:
    return pd.DataFrame({"ts_utc": hourly(ts(2026, 11, 2), n), "close": np.full(n, 1.0)})


def test_financing_charged_only_when_held_and_only_if_set():
    bars = flat_bars(24 * 7)
    base = CostModel(spread_pips=0.0, pip_size=1e-4, ref_price=1.0, commission_per_side=0.0)
    fee = CostModel(spread_pips=0.0, pip_size=1e-4, ref_price=1.0, commission_per_side=0.0,
                    financing_annual=0.0365)
    assert run_backtest(bars, Always(1.0), base, 24 * 252).net_returns.sum() == 0.0
    held = run_backtest(bars, Always(1.0), fee, 24 * 252).net_returns.sum()
    assert held == pytest.approx(-7 * 0.0365 / 365)    # Mon-Fri, Wednesday triple = 7 nights
    assert run_backtest(bars, Always(0.0), fee, 24 * 252).net_returns.sum() == 0.0
