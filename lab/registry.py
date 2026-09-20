"""The experiment registry: every run reproducible from its own row.

`trials` counts candidates for the multiple-testing bar. `episodes` holds the narrative and the
verdict. This table holds the MECHANICS: which code, which data, which costs, which latency
assumptions, which seeds. A result that cannot be re-run from its row is not a result.
"""
from __future__ import annotations

import json
import platform
import sqlite3
import time
import uuid

from research.episodes import code_commit, data_hash

DB = "data/research.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id  TEXT PRIMARY KEY,
    created_ts     REAL NOT NULL,
    kind           TEXT NOT NULL,          -- backtest | replay | paper | live
    question       TEXT NOT NULL,
    hypothesis     TEXT,
    strategy       TEXT,
    strategy_version TEXT,
    model_version  TEXT,
    instruments    TEXT,
    period_start   TEXT,
    period_end     TEXT,
    data_hash      TEXT,
    dataset_rows   INTEGER,
    cost_model     TEXT,
    latency_model  TEXT,
    config_json    TEXT,
    seeds          TEXT,
    code_commit    TEXT,
    machine        TEXT,
    status         TEXT NOT NULL,          -- running | complete | failed
    result_json    TEXT,
    verdict        TEXT,
    reason         TEXT,
    capital_allocated_zar REAL DEFAULT 0,
    capital_at_risk_zar   REAL DEFAULT 0,
    realised_pnl_zar      REAL,
    information_gained    TEXT,
    next_experiment       TEXT
);

CREATE TABLE IF NOT EXISTS latency_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    ts_utc     REAL NOT NULL,
    stage      TEXT NOT NULL,
    strategy   TEXT, model TEXT, instrument TEXT, exchange TEXT,
    node       TEXT, mode TEXT, regime TEXT,
    value_ms   REAL NOT NULL,
    span_id    TEXT, parent_span_id TEXT
);

CREATE TABLE IF NOT EXISTS clock_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc REAL NOT NULL,
    server TEXT NOT NULL,
    offset_ms REAL NOT NULL,
    round_trip_ms REAL NOT NULL,
    node TEXT
);

CREATE TABLE IF NOT EXISTS edge_decay (
    experiment_id TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    instrument TEXT NOT NULL,
    requested_delay_s REAL NOT NULL,
    effective_delay_s REAL,
    skipped    TEXT,
    gross_return REAL, net_return REAL, ev_per_trade REAL, win_rate REAL,
    profit_factor REAL, sharpe REAL, max_dd REAL,
    spread_and_fees REAL, financing REAL, delay_slippage_bps REAL,
    n_trades INTEGER, n_obs INTEGER,
    PRIMARY KEY (experiment_id, strategy, instrument, requested_delay_s)
);
"""


def _conn(db: str = DB) -> sqlite3.Connection:
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    return c


def new_id() -> str:
    """Time-ordered so the registry sorts chronologically without a join."""
    return f"exp_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:6]}"


def start(kind: str, question: str, **fields) -> str:
    eid = new_id()
    row = {"experiment_id": eid, "created_ts": time.time(), "kind": kind,
           "question": question, "code_commit": code_commit(),
           "machine": f"{platform.node()} {platform.system()} {platform.machine()}",
           "status": "running"}
    for k, v in fields.items():
        row[k] = json.dumps(v, default=str) if isinstance(v, (dict, list)) else v
    c = _conn()
    try:
        cols = ",".join(row)
        c.execute(f"INSERT INTO experiments ({cols}) VALUES ({','.join('?' * len(row))})",
                  tuple(row.values()))
        c.commit()
    finally:
        c.close()
    return eid


def finish(experiment_id: str, status: str = "complete", **fields) -> None:
    fields["status"] = status
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, default=str) if isinstance(v, (dict, list)) else v
            for v in fields.values()]
    c = _conn()
    try:
        c.execute(f"UPDATE experiments SET {sets} WHERE experiment_id=?", (*vals, experiment_id))
        c.commit()
    finally:
        c.close()


def save_decay(experiment_id: str, strategy: str, instrument: str, curve) -> None:
    cols = ["requested_delay_s", "effective_delay_s", "skipped", "gross_return", "net_return",
            "ev_per_trade", "win_rate", "profit_factor", "sharpe", "max_dd",
            "spread_and_fees", "financing", "delay_slippage_bps", "n_trades", "n_obs"]
    c = _conn()
    try:
        for _, r in curve.iterrows():
            vals = [r.get(k) if k in r and r.get(k) == r.get(k) else None for k in cols]
            c.execute(
                f"INSERT OR REPLACE INTO edge_decay (experiment_id, strategy, instrument,"
                f"{','.join(cols)}) VALUES (?,?,?,{','.join('?' * len(cols))})",
                (experiment_id, strategy, instrument, *vals))
        c.commit()
    finally:
        c.close()


def record_latency(stage: str, value_ms: float, experiment_id: str | None = None,
                   **attribution) -> None:
    """One latency observation, attributable. Distributions come from many of these."""
    c = _conn()
    try:
        c.execute("INSERT INTO latency_events (experiment_id, ts_utc, stage, strategy, model, "
                  "instrument, exchange, node, mode, regime, value_ms, span_id, parent_span_id)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (experiment_id, time.time(), stage, attribution.get("strategy"),
                   attribution.get("model"), attribution.get("instrument"),
                   attribution.get("exchange"), attribution.get("node", platform.node()),
                   attribution.get("mode"), attribution.get("regime"), float(value_ms),
                   attribution.get("span_id"), attribution.get("parent_span_id")))
        c.commit()
    finally:
        c.close()


def record_clock(samples) -> tuple:
    """Store NTP samples and return (offset_ms, uncertainty_ms). Drift is the series of these."""
    from lab.clock import consensus
    c = _conn()
    try:
        for s in samples:
            c.execute("INSERT INTO clock_samples (ts_utc, server, offset_ms, round_trip_ms, node)"
                      " VALUES (?,?,?,?,?)",
                      (s.ts_utc, s.server, s.offset_ms, s.round_trip_ms, platform.node()))
        c.commit()
    finally:
        c.close()
    return consensus(samples)


def clock_drift(db: str = DB) -> dict:
    """How much the local clock has moved against true time across recorded samples."""
    c = _conn(db)
    try:
        rows = c.execute("SELECT ts_utc, offset_ms FROM clock_samples ORDER BY ts_utc").fetchall()
    finally:
        c.close()
    if len(rows) < 2:
        return {"n": len(rows)}
    span_h = (rows[-1][0] - rows[0][0]) / 3600.0
    if span_h < 0.5:
        # Dividing a few milliseconds of noise by a few seconds of span produced a reported
        # drift of 27 seconds per hour. Drift needs a baseline, not two adjacent samples.
        return {"n": len(rows), "span_hours": span_h,
                "drift_ms_per_hour": None,
                "note": "span too short to estimate drift; need at least 30 minutes"}
    return {"n": len(rows), "first_offset_ms": rows[0][1], "last_offset_ms": rows[-1][1],
            "span_hours": span_h,
            "drift_ms_per_hour": (rows[-1][1] - rows[0][1]) / span_h if span_h else 0.0}


def percentiles(stage: str | None = None, db: str = DB) -> dict:
    """Distributions, not averages: the brief's requirement, from whatever has been recorded."""
    import numpy as np
    c = _conn(db)
    try:
        q = "SELECT value_ms FROM latency_events" + (" WHERE stage=?" if stage else "")
        vals = [r[0] for r in c.execute(q, (stage,) if stage else ())]
    finally:
        c.close()
    if not vals:
        return {}
    a = np.array(vals, dtype=float)
    return {"n": len(a), "min": float(a.min()), "median": float(np.median(a)),
            "p90": float(np.percentile(a, 90)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "max": float(a.max()),
            "jitter_iqr": float(np.percentile(a, 75) - np.percentile(a, 25)),
            "outliers_over_p99": int((a > np.percentile(a, 99)).sum())}


__all__ = ["start", "finish", "save_decay", "record_latency", "percentiles", "new_id",
           "data_hash", "DB"]
