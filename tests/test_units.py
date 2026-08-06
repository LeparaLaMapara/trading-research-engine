"""Pip math and time bucketing — the numbers everything downstream trusts.

Prices use a FIXED 10**5 scale (see telemetry.units), so raw values below are the real
price * 1e5, and pip math depends on pip_position, not on the symbol's digits.
"""
from datetime import datetime, timezone

from telemetry import units


def test_spread_pips_eurusd():
    # EURUSD real ~1.15380/1.15388, pip_position 4: raw spread 8 -> 0.8 pips
    assert units.spread_pips(115380, 115388, 4) == 0.8


def test_spread_pips_usdjpy():
    # USDJPY real ~158.430/158.440 (raw *1e5), pip_position 2: raw spread 1000 -> 1.0 pip
    assert units.spread_pips(15843000, 15844000, 2) == 1.0


def test_spread_pips_xauusd():
    # XAUUSD real ~4236.20/4236.70 (raw *1e5), pip_position 2: raw spread 50000 -> 50 pips
    assert units.spread_pips(423620000, 423670000, 2) == 50.0


def test_to_price_fixed_scale():
    assert units.to_price(115388) == 1.15388
    assert units.to_price(15843642) == 158.43642     # USDJPY: /1e5, NOT /1e3
    assert round(units.to_price(423620357), 2) == 4236.20  # XAUUSD


def test_cross_consistency_audjpy():
    # The proof the scale is 1e5: AUDJPY == AUDUSD * USDJPY under /1e5.
    audusd = units.to_price(70290)        # 0.7029
    usdjpy = units.to_price(15843642)     # 158.436
    audjpy = units.to_price(11135700)     # 111.357
    assert abs(audjpy - audusd * usdjpy) < 0.05


def test_to_sast_offset():
    dt = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    sast = units.to_sast(dt)
    assert sast.hour == 12
    assert sast.utcoffset().total_seconds() == 2 * 3600


def test_hour_of_week():
    # 2026-01-01 is a Thursday (weekday 3); 12:00 SAST -> 3*24+12 = 84
    dt = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert units.hour_of_week(units.to_sast(dt)) == 84
