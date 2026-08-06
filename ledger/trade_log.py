"""SARS-ready trade log. Schema built now; rows written from first live trade onward.

Every execution (including Phase 1a-active probe trades) is recorded here. The account
is live, so trades are real taxable events and record-keeping starts immediately.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_log (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc REAL NOT NULL,
    ts_sast TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,               -- BUY | SELL
    order_type TEXT NOT NULL,         -- MARKET | LIMIT | ...
    volume_lots REAL,
    requested_price REAL,
    filled_price REAL,
    slippage_pips REAL,
    stop_loss REAL,
    take_profit REAL,
    commission REAL,
    swap REAL,
    gross_pnl REAL,
    net_pnl REAL,
    order_id INTEGER,
    deal_id INTEGER,
    position_id INTEGER,
    status TEXT,                      -- FILLED | REJECTED | REQUOTED | ...
    purpose TEXT,                     -- e.g. 'telemetry_probe' | 'strategy'
    note TEXT
);
"""


class TradeLog:
    def __init__(self, db_path: str = "data/trade_log.db") -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def record(self, **fields: Any) -> int:
        fields.setdefault("ts_utc", time.time())
        cols = list(fields.keys())
        cur = self.conn.execute(
            f"INSERT INTO trade_log ({','.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)})", tuple(fields.values()))
        self.conn.commit()
        return int(cur.lastrowid)

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
