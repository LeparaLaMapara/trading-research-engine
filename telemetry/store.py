"""SQLite storage for telemetry + reproducible Parquet snapshots.

Design for §5 (reproducibility): the dataset content hash is computed over a CANONICAL
serialization of the sorted rows, not over the Parquet container (whose bytes can vary
with library metadata). So the hash is a pure function of the data, and re-exporting the
same rows always yields the same hash. The manifest records (path, rows, sha256,
code_version, min/max ts) for every snapshot.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import time
from typing import Any

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc REAL NOT NULL,
    ts_sast TEXT NOT NULL,
    dow_sast INTEGER NOT NULL,
    hour_sast INTEGER NOT NULL,
    hour_of_week INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    bid_raw INTEGER,
    ask_raw INTEGER,
    digits INTEGER NOT NULL,
    pip_position INTEGER NOT NULL,
    bid REAL,
    ask REAL,
    spread_price REAL,
    spread_pips REAL,
    side TEXT NOT NULL,
    server_ts REAL,
    recv_latency_ms REAL
);
CREATE INDEX IF NOT EXISTS ix_ticks_symbol_how ON ticks(symbol, hour_of_week);

CREATE TABLE IF NOT EXISTS latency (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc REAL NOT NULL,
    probe TEXT NOT NULL,
    rtt_ms REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_spec (
    symbol TEXT PRIMARY KEY,
    symbol_id INTEGER,
    digits INTEGER,
    pip_position INTEGER,
    lot_size INTEGER,
    min_volume INTEGER,
    step_volume INTEGER,
    max_volume INTEGER,
    swap_long REAL,
    swap_short REAL,
    captured_ts REAL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    rows INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    code_version TEXT,
    min_ts REAL,
    max_ts REAL,
    created_ts REAL NOT NULL
);
"""

# Columns hashed/exported, in fixed order — the canonical dataset definition.
TICK_COLS = [
    "ts_utc", "ts_sast", "dow_sast", "hour_sast", "hour_of_week", "symbol",
    "bid_raw", "ask_raw", "digits", "pip_position", "bid", "ask",
    "spread_price", "spread_pips", "side",
]

#: Added 2026-09-20 for the latency lab. ProtoOASpotEvent carries the BROKER's own stamp for
#: the event; without it "market data latency" is unmeasurable and we were discarding it.
#:
#: They are deliberately OUTSIDE TICK_COLS, which is the canonical hashed column set. Adding a
#: column to the hash would change the content hash of the same underlying ticks, silently
#: invalidating every snapshot digest recorded before today. The hash defines the dataset; new
#: instrumentation travels alongside it.
TICK_EXTRA_COLS = ["server_ts", "recv_latency_ms"]
ALL_TICK_COLS = TICK_COLS + TICK_EXTRA_COLS


def _code_version() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def content_hash(df: pd.DataFrame) -> str:
    """Deterministic sha256 over the sorted rows. Pure function of the data."""
    ordered = df[TICK_COLS].sort_values(["ts_utc", "symbol"]).reset_index(drop=True)
    canonical = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class Store:
    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._uncommitted = 0

    # -- writes ------------------------------------------------------------
    def insert_tick(self, row: dict[str, Any]) -> None:
        for c in TICK_EXTRA_COLS:
            row.setdefault(c, None)
        self.conn.execute(
            f"INSERT INTO ticks ({','.join(ALL_TICK_COLS)}) "
            f"VALUES ({','.join(':' + c for c in ALL_TICK_COLS)})", row)
        self._tick_commit()

    def insert_latency(self, probe: str, rtt_ms: float) -> None:
        self.conn.execute("INSERT INTO latency (ts_utc, probe, rtt_ms) VALUES (?,?,?)",
                          (time.time(), probe, rtt_ms))
        self._tick_commit()

    def upsert_symbol_spec(self, spec: dict[str, Any]) -> None:
        cols = ["symbol", "symbol_id", "digits", "pip_position", "lot_size",
                "min_volume", "step_volume", "max_volume", "swap_long", "swap_short",
                "captured_ts"]
        self.conn.execute(
            f"INSERT OR REPLACE INTO symbol_spec ({','.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)})",
            tuple(spec.get(c) for c in cols))
        self.conn.commit()

    # Commit on COUNT or on TIME, whichever comes first. Count alone was enough to make a
    # working logger indistinguishable from a broken one: in a quiet session (after the New
    # York close, 14 spot events in 80 seconds was measured) the buffer takes many minutes to
    # reach 100, so the table sits frozen and the only way to tell the difference is to wait.
    # On this project that ambiguity has been expensive.
    COMMIT_EVERY_TICKS = 100
    COMMIT_EVERY_SECONDS = 20.0

    def _tick_commit(self) -> None:
        self._uncommitted += 1
        now = time.time()
        last = getattr(self, "_last_commit_ts", None)
        if last is None:
            self._last_commit_ts = now
            last = now
        if (self._uncommitted >= self.COMMIT_EVERY_TICKS
                or now - last >= self.COMMIT_EVERY_SECONDS):
            self.conn.commit()
            self._uncommitted = 0
            self._last_commit_ts = now

    def commit(self) -> None:
        self.conn.commit()
        self._uncommitted = 0

    # -- snapshot ----------------------------------------------------------
    def snapshot(self, out_dir: str, seed: int = 0) -> dict[str, Any] | None:
        """Export all ticks to a Parquet file, hash the content, record the manifest."""
        self.commit()
        df = pd.read_sql_query("SELECT * FROM ticks", self.conn)
        if df.empty:
            print("snapshot: no ticks to export.")
            return None
        digest = content_hash(df)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"ticks_{digest[:12]}.parquet")
        df[TICK_COLS].sort_values(["ts_utc", "symbol"]).reset_index(drop=True) \
            .to_parquet(path, index=False)
        manifest = {
            "path": path, "rows": int(len(df)), "sha256": digest,
            "code_version": _code_version(),
            "min_ts": float(df["ts_utc"].min()), "max_ts": float(df["ts_utc"].max()),
            "created_ts": time.time(),
        }
        self.conn.execute(
            "INSERT INTO snapshots (path, rows, sha256, code_version, min_ts, max_ts, created_ts) "
            "VALUES (:path,:rows,:sha256,:code_version,:min_ts,:max_ts,:created_ts)", manifest)
        self.conn.commit()
        print(f"snapshot: {manifest['rows']} rows -> {path}  sha256={digest[:12]}…")
        return manifest

    def close(self) -> None:
        self.commit()
        self.conn.close()
