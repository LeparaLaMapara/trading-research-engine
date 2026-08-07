"""Persist Transfer Cards (fetched papers + their mapping). Part of the permanent memory.

Stores the fetched abstract text alongside the resolvable identifier, so every claim is
traceable to real, retrieved source material (spec §5).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from research.schemas import TransferCard

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfer_cards (
    id TEXT PRIMARY KEY,
    identifier TEXT,
    title TEXT,
    discipline TEXT,
    url TEXT,
    market_claim TEXT,
    abstract TEXT,
    mapped_kind TEXT,
    mapped_params TEXT,
    assumptions TEXT,
    failure_regime TEXT,
    created_ts REAL
);
CREATE INDEX IF NOT EXISTS ix_cards_identifier ON transfer_cards(identifier);
"""


class CardStore:
    def __init__(self, db_path: str = "data/research.db") -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save(self, card: TransferCard, created_ts: float | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO transfer_cards "
            "(id, identifier, title, discipline, url, market_claim, abstract, mapped_kind, "
            "mapped_params, assumptions, failure_regime, created_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (card.id, card.identifier, card.title, card.discipline, card.url, card.market_claim,
             card.abstract, card.mapped_kind, json.dumps(card.mapped_params),
             json.dumps(card.assumptions_required), card.failure_regime,
             created_ts if created_ts is not None else time.time()))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM transfer_cards").fetchone()[0]

    def all(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM transfer_cards ORDER BY created_ts DESC")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
