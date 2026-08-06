"""Session filter derived from MEASURED telemetry, not from theory.

The classic advice ("trade the London/New York overlap") is a hypothesis. This module
instead reads the broker's own logged spreads and keeps only the hour-of-week buckets that
were actually cheapest for our account. The filter is then applied by zeroing out positions
outside those hours.
"""
from __future__ import annotations

import sqlite3
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings

_SAST = ZoneInfo(settings.SAST)


def derive_cheap_hours(
    telemetry_db: str,
    symbol: str,
    max_spread_pips: float | None = None,
    top_frac: float = 0.5,
) -> set[int]:
    """Return the cheapest hour_of_week buckets for a symbol from logged spreads.

    Reads ticks for the symbol, takes the median spread_pips per hour_of_week, then:
    - if max_spread_pips is given, keeps every hour whose median is at or below it;
    - otherwise keeps the cheapest top_frac fraction of hours that have data.

    Falls back to allowing all 168 hours when telemetry is empty or missing, so a sparse db
    never silently blocks all trading.
    """
    all_hours = set(range(168))
    try:
        conn = sqlite3.connect(telemetry_db)
        try:
            df = pd.read_sql_query(
                "SELECT hour_of_week, spread_pips FROM ticks WHERE symbol = ?",
                conn,
                params=(symbol,),
            )
        finally:
            conn.close()
    except Exception:
        return all_hours

    df = df.dropna(subset=["hour_of_week", "spread_pips"])
    if df.empty:
        return all_hours

    med = df.groupby("hour_of_week")["spread_pips"].median().sort_values()

    if max_spread_pips is not None:
        cheap = med[med <= max_spread_pips].index
    else:
        frac = min(max(top_frac, 0.0), 1.0)
        keep = max(1, int(round(len(med) * frac)))
        cheap = med.iloc[:keep].index

    hours = {int(h) for h in cheap}
    return hours or all_hours


def _hour_of_week_sast(ts_utc: pd.Series) -> pd.Series:
    """Epoch seconds (UTC) -> SAST hour_of_week (Mon 00:00 SAST = 0)."""
    dt = pd.to_datetime(ts_utc, unit="s", utc=True).dt.tz_convert(_SAST)
    return (dt.dt.weekday * 24 + dt.dt.hour).astype(int)


class SessionFilter:
    """Zero out positions on bars whose SAST hour_of_week is not allowed."""

    def __init__(self, allowed_hours_of_week: set[int]):
        self.allowed_hours_of_week = set(allowed_hours_of_week)

    def apply(self, bars: pd.DataFrame, positions: pd.Series) -> pd.Series:
        """Return positions masked to 0 outside the allowed hours (same index)."""
        how = _hour_of_week_sast(bars["ts_utc"])
        allowed_mask = how.isin(self.allowed_hours_of_week).to_numpy()
        masked = positions.where(pd.Series(allowed_mask, index=positions.index), 0)
        return masked
