"""The permanent Failure Registry (spec §10).

Every strategy that dies leaves a tombstone here so the same dead end is never re-proposed.
This is plain deterministic storage. It records lessons; it does not decide anything.
"""
from __future__ import annotations

import os
import sqlite3
import time


class FailureRegistry:
    """SQLite-backed registry of killed strategies and their lessons."""

    def __init__(self, db_path: str = "data/research.db") -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failures (
                    failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_kind TEXT,
                    symbol TEXT,
                    killed_at_stage TEXT,
                    cause_category TEXT,
                    plain_english TEXT,
                    generalisable_lesson TEXT,
                    proposing_agent TEXT,
                    created_ts REAL
                )
                """
            )

    def add(self, **fields) -> int:
        """Record a failure. `created_ts` may be passed in for determinism; defaults to now."""
        created_ts = fields.get("created_ts")
        if created_ts is None:
            created_ts = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO failures (
                    strategy_kind, symbol, killed_at_stage, cause_category,
                    plain_english, generalisable_lesson, proposing_agent, created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields.get("strategy_kind"),
                    fields.get("symbol"),
                    fields.get("killed_at_stage"),
                    fields.get("cause_category"),
                    fields.get("plain_english"),
                    fields.get("generalisable_lesson"),
                    fields.get("proposing_agent"),
                    created_ts,
                ),
            )
            return int(cur.lastrowid)

    def all(self) -> list[dict]:
        """Every recorded failure, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM failures ORDER BY failure_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def matches(
        self, kind: str, symbol: str, cause_category: str | None = None
    ) -> list[dict]:
        """Prior failures with the same kind+symbol (and cause if given). Used to auto-reject."""
        sql = "SELECT * FROM failures WHERE strategy_kind = ? AND symbol = ?"
        params: list = [kind, symbol]
        if cause_category is not None:
            sql += " AND cause_category = ?"
            params.append(cause_category)
        sql += " ORDER BY failure_id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict:
        """Counts of failures grouped by cause_category."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cause_category, COUNT(*) AS n FROM failures GROUP BY cause_category"
            ).fetchall()
        return {r["cause_category"]: int(r["n"]) for r in rows}
