"""Convert a quote currency into the account currency (USD), from stored daily closes.

Sizing needs the dollar value of a pip. A pip moves the price in the QUOTE currency, so a
yen-quoted pip is worth about 1/150 of a dollar-quoted one. The rate here is the latest D1
close in data/market.db: up to a day old, which moves a stop's dollar value by a percent or
two. That is small next to a 6% risk limit, and it is stated rather than hidden.

Unknown currency means None, never a guess: sizing refuses when it cannot state the risk.
"""
from __future__ import annotations

import sqlite3

ACCOUNT = "USD"


def _last_close(conn: sqlite3.Connection, symbol: str) -> float | None:
    row = conn.execute("SELECT close FROM bars WHERE symbol=? AND period='D1' "
                       "ORDER BY ts_utc DESC LIMIT 1", (symbol,)).fetchone()
    return float(row[0]) if row and row[0] else None


def quote_to_account(quote: str, db: str = "data/market.db") -> float | None:
    """USD per one unit of `quote`, or None when no stored pair converts it."""
    quote = quote.upper()
    if quote == ACCOUNT:
        return 1.0
    conn = sqlite3.connect(db)
    try:
        direct = _last_close(conn, f"{quote}{ACCOUNT}")      # e.g. GBPUSD
        if direct:
            return direct
        inverse = _last_close(conn, f"{ACCOUNT}{quote}")     # e.g. USDJPY
        if inverse:
            return 1.0 / inverse
        return None
    finally:
        conn.close()
