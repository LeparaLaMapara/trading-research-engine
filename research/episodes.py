"""Research episodes: durable lineage for every conclusion the engine reaches.

An episode answers, after the agent that produced it is gone: what was asked, what we believed
beforehand, what was run (code and data identity), what came back, what we concluded, and
what to ask next. Conclusions that live only in a chat transcript are one context window from
gone; this table is where they go instead.

The verdict vocabulary is closed on purpose. "Bad strategy" hides the difference between an
idea that was tested and lost (FALSIFIED), one the data could not decide (UNDERPOWERED), one
that could not be scored at all (UNEVALUABLE), and one we never had the data for
(DATA_FAILURE). Those lead to very different next steps.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time

DB = "data/research.db"

VERDICTS = frozenset({
    "FALSIFIED", "UNDERPOWERED", "UNEVALUABLE", "TOO_EXPENSIVE", "IMPLEMENTATION_FAILURE",
    "DATA_FAILURE", "SUPERSEDED", "UNRESOLVED", "SURVIVED",
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    programme      TEXT NOT NULL,
    question       TEXT NOT NULL,
    claim          TEXT,
    prior          TEXT,
    source         TEXT,
    experiment     TEXT,
    code_commit    TEXT,
    data_hash      TEXT,
    evidence_json  TEXT,
    verdict        TEXT NOT NULL,
    belief_update  TEXT,
    revisit_if     TEXT,
    next_question  TEXT,
    created_ts     REAL NOT NULL
);
"""


def code_commit() -> str:
    """The commit the experiment ran from, marked dirty if the tree had local changes."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def data_hash(obj) -> str:
    """Short sha256 of any JSON-serialisable description of the data used."""
    blob = json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def record(programme: str, question: str, verdict: str, *, claim: str = "", prior: str = "",
           source: str = "", experiment: str = "", data: str = "", evidence: dict | None = None,
           belief_update: str = "", revisit_if: str = "", next_question: str = "",
           db: str = DB) -> int:
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}; use one of {sorted(VERDICTS)}")
    c = sqlite3.connect(db)
    try:
        c.executescript(SCHEMA)
        cur = c.execute(
            "INSERT INTO episodes (programme, question, claim, prior, source, experiment, "
            "code_commit, data_hash, evidence_json, verdict, belief_update, revisit_if, "
            "next_question, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (programme, question, claim, prior, source, experiment, code_commit(), data,
             json.dumps(evidence or {}, default=str), verdict, belief_update, revisit_if,
             next_question, time.time()))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def load(programme: str | None = None, db: str = DB) -> list[dict]:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        q = "SELECT * FROM episodes" + (" WHERE programme=?" if programme else "") + \
            " ORDER BY episode_id"
        return [dict(r) for r in c.execute(q, (programme,) if programme else ())]
    finally:
        c.close()
