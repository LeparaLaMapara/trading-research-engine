"""Pure functions for price/pip math and time bucketing. No I/O — trivially testable.

cTrader sends spot prices as integers scaled by a FIXED 10**5, regardless of the
symbol's `digits`. (Verified empirically: AUDJPY raw == AUDUSD_real * USDJPY_real only
under the 10**5 scale, not under 10**digits.) So:

    real_price  = raw / 1e5
    spread_pips = (ask_raw - bid_raw) * 10**(pip_position - 5)

`digits` is retained as symbol metadata (for display rounding), but is NOT the price
scale. This is the trap the existing ctrader-connect streamer avoids only because it
hardcodes /1e5 and streams a 5-digit symbol.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SAST = ZoneInfo("Africa/Johannesburg")

PRICE_SCALE_EXP = 5
PRICE_SCALE = 10 ** PRICE_SCALE_EXP     # 100_000 — fixed, all symbols


def to_price(raw: int) -> float:
    """Integer feed price -> real price (fixed 10**5 scale)."""
    return raw / PRICE_SCALE


def spread_price(bid_raw: int, ask_raw: int) -> float:
    """Spread in real-price terms."""
    return (ask_raw - bid_raw) / PRICE_SCALE


def spread_pips(bid_raw: int, ask_raw: int, pip_position: int) -> float:
    """Spread in pips: real spread divided by pip size (10**-pip_position)."""
    return (ask_raw - bid_raw) * (10 ** (pip_position - PRICE_SCALE_EXP))


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_sast(dt_utc: datetime) -> datetime:
    """Convert a tz-aware UTC datetime to SAST (Africa/Johannesburg, UTC+2, no DST)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(SAST)


def hour_of_week(dt_sast: datetime) -> int:
    """0..167. Monday 00:00 SAST = 0; Sunday 23:00 SAST = 167. weekday(): Mon=0."""
    return dt_sast.weekday() * 24 + dt_sast.hour
