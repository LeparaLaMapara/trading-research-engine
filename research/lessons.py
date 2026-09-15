"""Semantic memory: what the engine has learned, and proof it was worth remembering.

This is the part that makes the system improve rather than merely persist. The failure
registry remembers *what was tried*. This remembers *what to do differently*, and, crucially,
measures whether remembering it actually helped.

The design follows what the evidence supports, not what sounds impressive:

  * **A verifier comes first.** Reflection and memory improve an agent only where a cheap,
    reliable oracle exists; without one, self-correction measurably degrades performance
    (Huang et al., ICLR 2024). This engine has a rare one: the walk-forward plus deflated
    Sharpe gate. Lessons are therefore scored against it, never against an opinion.

  * **Delta updates, never a rewrite.** Each cycle appends or amends individual lessons.
    Rewriting the whole playbook each time causes "context collapse", where the distilled
    text drifts into generic advice and loses the specifics that made it useful.

  * **Every lesson carries a win rate, and losers are evicted.** A lesson that has been in
    context N times without ever coinciding with a better outcome is deleted. This is the
    part most memory systems skip, and skipping it is why they degrade: context rot means an
    ever-growing pile of text makes the model WORSE, not better, so memory that cannot prove
    its worth is a liability rather than an asset.

  * **Bounded.** The injected playbook is capped. Unbounded memory is the failure mode.

Attribution is deliberately crude and honest: a lesson that was on screen during a cycle
which beat the engine's historical best is credited. Crude attribution that is measured beats
sophisticated attribution that is assumed.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time

# The playbook handed to the proposer is capped. More context is not more help.
MAX_ACTIVE_LESSONS = 8
# A lesson gets this many airings to prove itself before it can be retired.
MIN_TRIALS_BEFORE_EVICTION = 12
# Below this hit rate, after enough trials, it is noise and gets retired.
MIN_HELPED_RATE = 0.10


def _fingerprint(text: str) -> str:
    """Identity of a lesson, so the same insight is amended rather than duplicated."""
    norm = re.sub(r"[^a-z0-9 ]", "", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


class LessonStore:
    """SQLite-backed lessons with usage statistics. Plain storage; it decides nothing."""

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
                CREATE TABLE IF NOT EXISTS lessons (
                    fingerprint  TEXT PRIMARY KEY,
                    lesson       TEXT NOT NULL,
                    evidence     TEXT,
                    category     TEXT,
                    times_seen   INTEGER NOT NULL DEFAULT 0,
                    times_helped INTEGER NOT NULL DEFAULT 0,
                    retired      INTEGER NOT NULL DEFAULT 0,
                    created_ts   REAL,
                    updated_ts   REAL
                )
                """
            )

    # ------------------------------------------------------------------ writing

    def add(self, lesson: str, evidence: str = "", category: str = "",
            now: float | None = None) -> str:
        """Append a lesson, or amend the evidence on one already known.

        Amending rather than replacing is the delta-update rule: the same insight seen again
        gains supporting evidence instead of overwriting what made it specific.
        """
        fp = _fingerprint(lesson)
        ts = now if now is not None else time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT fingerprint, evidence FROM lessons WHERE fingerprint=?",
                               (fp,)).fetchone()
            if row:
                merged = row["evidence"] or ""
                if evidence and evidence not in merged:
                    merged = (merged + " | " + evidence).strip(" |")[:2000]
                conn.execute("UPDATE lessons SET evidence=?, updated_ts=?, retired=0 "
                             "WHERE fingerprint=?", (merged, ts, fp))
            else:
                conn.execute(
                    "INSERT INTO lessons (fingerprint, lesson, evidence, category, "
                    "created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?)",
                    (fp, lesson.strip(), evidence, category, ts, ts))
        return fp

    def mark_shown(self, fingerprints: list[str]) -> None:
        """These were in context for a cycle. The denominator of the win rate."""
        if not fingerprints:
            return
        with self._connect() as conn:
            conn.executemany("UPDATE lessons SET times_seen = times_seen + 1 "
                             "WHERE fingerprint=?", [(f,) for f in fingerprints])

    def mark_helped(self, fingerprints: list[str]) -> None:
        """The cycle these were shown in beat the historical best. The numerator."""
        if not fingerprints:
            return
        with self._connect() as conn:
            conn.executemany("UPDATE lessons SET times_helped = times_helped + 1 "
                             "WHERE fingerprint=?", [(f,) for f in fingerprints])

    def evict(self, min_trials: int = MIN_TRIALS_BEFORE_EVICTION,
              min_rate: float = MIN_HELPED_RATE) -> list[str]:
        """Retire lessons that have had a fair hearing and never helped.

        Without this the store only grows, and a growing pile of unproven text degrades the
        model it is meant to help. Retired rather than deleted, so the fact that it was tried
        and found useless is itself remembered and it cannot be silently re-learned.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT fingerprint FROM lessons WHERE retired=0 AND times_seen >= ? "
                "AND (CAST(times_helped AS REAL) / times_seen) < ?",
                (min_trials, min_rate)).fetchall()
            dead = [r["fingerprint"] for r in rows]
            if dead:
                conn.executemany("UPDATE lessons SET retired=1, updated_ts=? "
                                 "WHERE fingerprint=?",
                                 [(time.time(), f) for f in dead])
        return dead

    # ------------------------------------------------------------------ reading

    def active(self, limit: int = MAX_ACTIVE_LESSONS) -> list[dict]:
        """The playbook to inject: best proven first, then untested newcomers.

        Untested lessons rank above proven-useless ones so a new insight gets its hearing,
        but the cap means they compete for a fixed number of slots rather than accumulating.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *, CASE WHEN times_seen = 0 THEN NULL
                               ELSE CAST(times_helped AS REAL) / times_seen END AS helped_rate
                FROM lessons WHERE retired = 0
                ORDER BY (times_seen = 0) DESC, helped_rate DESC, times_helped DESC
                LIMIT ?
                """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def all(self, include_retired: bool = True) -> list[dict]:
        sql = ("SELECT *, CASE WHEN times_seen = 0 THEN NULL ELSE "
               "CAST(times_helped AS REAL) / times_seen END AS helped_rate FROM lessons")
        if not include_retired:
            sql += " WHERE retired = 0"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql + " ORDER BY updated_ts DESC")]

    def summary(self) -> dict:
        with self._connect() as conn:
            r = conn.execute(
                "SELECT COUNT(*) n, SUM(retired) retired, SUM(times_seen) seen, "
                "SUM(times_helped) helped FROM lessons").fetchone()
        return {"lessons": int(r["n"] or 0), "retired": int(r["retired"] or 0),
                "times_shown": int(r["seen"] or 0), "times_helped": int(r["helped"] or 0)}


def lessons_from_cycle(trials: list[dict], symbol: str, honest_n: int) -> list[tuple[str, str]]:
    """Distil a finished cycle into lessons, DETERMINISTICALLY.

    No model writes these. They are statements about what the verifier actually returned, so
    every one is checkable against the trial record. A lesson the engine cannot prove is a
    lesson it should not be carrying.
    """
    out: list[tuple[str, str]] = []
    tested = [t for t in trials if "wf" in t]
    if not tested:
        return out

    failed = [t for t in tested if t.get("verdict") == "FAIL"]
    if len(failed) == len(tested):
        out.append((
            f"On {symbol}, every idea tested so far has lost money once real trading costs "
            f"were counted.",
            f"{len(tested)} tested this cycle, {len(failed)} failed, {honest_n} tried in total."))

    # Which families keep dying, and how badly.
    by_kind: dict[str, list[float]] = {}
    for t in tested:
        by_kind.setdefault(t["proposal"].kind, []).append(float(t.get("dsr") or 0.0))
    for kind, dsrs in by_kind.items():
        if dsrs and max(dsrs) < 0.05:
            out.append((
                f"The {kind.replace('_', ' ')} family is not close on {symbol}: its best "
                f"attempt is far below the bar, so small tweaks to it are unlikely to help.",
                f"best deflated Sharpe {max(dsrs):.3f} across {len(dsrs)} attempt(s)."))

    # A strategy that looked good in development and died out of sample is the single most
    # useful thing to remember, because it is overfitting caught in the act.
    for t in tested:
        dev = (t.get("wf", {}).get("dev_summary") or {}).get("sharpe")
        hold = (t.get("wf", {}).get("holdout_summary") or {}).get("sharpe")
        if dev is not None and hold is not None and dev > 0.5 and hold <= 0:
            out.append((
                f"A {t['proposal'].kind.replace('_', ' ')} setup on {symbol} looked good on "
                f"the data it was built from and lost money on data it had never seen. Treat "
                f"a good in-sample result on this family as a warning, not a finding.",
                f"development Sharpe {dev:.2f} vs holdout {hold:.2f}."))
    return out
