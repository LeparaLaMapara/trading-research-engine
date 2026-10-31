"""Entry guards: the moments the engine must not open a trade, whatever the signal says.

Three, each from something this engine measured or a release time fixed by law:

  * rollover: the broker rolls positions at 17:00 New York time (21:00 UTC in US summer, 22:00
    in winter). Measured spreads there run about 10 times the afternoon value (lab work,
    2026-09-20). No entry from 30 minutes before to 60 minutes after. Using New York time
    rather than a fixed UTC hour keeps the window right across daylight saving.
  * news: no entry 30 minutes either side of a high-impact release in a currency the
    instrument depends on (news/calendar.py). Fails closed when the week's calendar is missing.
  * spread: no entry while the live spread is more than SPREAD_MULT times this instrument's
    measured median (data/spread_summary.json). An instrument with no measured spread does
    not trade.

Exits are never blocked: a stop or a rule exit must always be able to run.

The guards only ever say no. Nothing here can open a trade or make one bigger.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from news import calendar as cal

NY = ZoneInfo("America/New_York")
ROLL_BEFORE_MIN, ROLL_AFTER_MIN = 30, 60
SPREAD_MULT = 2.0
SPREADS = "data/spread_summary.json"


def near_rollover(ts: float, before_min: int = ROLL_BEFORE_MIN,
                  after_min: int = ROLL_AFTER_MIN) -> bool:
    """True inside [17:00 NY - before, 17:00 NY + after]."""
    d = dt.datetime.fromtimestamp(ts, NY)
    for day in (d.date() - dt.timedelta(days=1), d.date(), d.date() + dt.timedelta(days=1)):
        roll = dt.datetime.combine(day, dt.time(17, 0), NY).timestamp()
        if roll - before_min * 60 <= ts <= roll + after_min * 60:
            return True
    return False


def reference_spread(symbol: str, path: str = SPREADS) -> float | None:
    try:
        with open(path, encoding="utf-8") as fh:
            row = json.load(fh).get(symbol.upper())
    except (OSError, ValueError):
        return None
    return float(row["spread_pips"]) if row and row.get("spread_pips") else None


def spread_reason(symbol: str, spread_pips: float, path: str = SPREADS,
                  mult: float = SPREAD_MULT) -> str | None:
    ref = reference_spread(symbol, path)
    if ref is None:
        return f"spread: no measured reference for {symbol} (fail closed)"
    if spread_pips > mult * ref:
        return f"spread: {spread_pips:.2f} pips is over {mult:g}x the measured {ref:.2f}"
    return None


def entry_check(symbol: str, ts: float, spread_pips: float | None = None,
                calendar: dict | None = None, spreads_path: str = SPREADS) -> list[str]:
    """Every reason `symbol` must not open at `ts`. An empty list means the guards allow it.

    `spread_pips` is the live spread at send time; when the caller has no quote yet (the hourly
    trader deciding whether to call the order tool at all) pass None and the order tool checks
    it again with the real quote.
    """
    reasons = []
    if near_rollover(ts):
        reasons.append("rollover: 17:00 New York, spreads wide")
    try:
        why = cal.blackout(symbol, ts, calendar)
    except KeyError as exc:
        why = f"news: {exc.args[0]} (fail closed)"
    if why:
        reasons.append(why)
    if spread_pips is not None:
        why = spread_reason(symbol, spread_pips, spreads_path)
        if why:
            reasons.append(why)
    return reasons
