"""The permanent Failure Registry (spec §10).

Every strategy that dies leaves a tombstone here so the same dead end is never re-proposed.
This is plain deterministic storage. It records lessons; it does not decide anything.

Design note (2026-09-15). The first version keyed rejection on (strategy_kind, symbol) and
ignored parameters, which made it a permanent veto: once six kinds had each failed once on
three symbols, the 18 tombstones covered the whole cross product and every later proposal was
skipped before it was ever tested. The loop ran green and learned nothing for five weeks.

A failure is evidence about a density, not a veto. The fix follows the standard structure
from tabu search and TPE:

  * RECENCY  (hard, auto-expiring)  keyed on the EXACT variant, i.e. the hash of
    kind+params+symbol+period. Re-running a deterministic backtest on the same data gives the
    same answer, so skipping it saves compute and costs nothing. The tenure expires, and it
    also lifts early once enough new bars exist for the answer to have changed.
  * FREQUENCY (soft, permanent)     a count per family. It PENALISES a family's score and
    steers the proposer away from it. It never forbids.
  * ASPIRATION                      a tabu variant runs anyway if its committed prediction
    beats the incumbent best. Without this, remembered failure becomes a blacklist again.

The registry also owns the honest trial count. Every candidate that reaches the scoring stage
is recorded, including ones skipped by tabu, because the multiple-testing correction is a
function of how many things were TRIED, not how many were reported. A registry that lets the
search run faster without counting those trials makes the overfitting worse, not better.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

# Trials a hard tabu on an exact variant survives before it expires on its own.
DEFAULT_TENURE = 100
# If the bar count for a symbol grows by this fraction, a stale backtest could genuinely
# come out differently, so the tabu lifts early.
DATA_GROWTH_LIFT = 0.10


def variant_hash(kind: str, params: dict | None, symbol: str, period: str) -> str:
    """Stable identity of an exact, re-runnable backtest. Order-insensitive over params."""
    payload = json.dumps(
        {"kind": kind, "params": params or {}, "symbol": symbol, "period": period},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class FailureRegistry:
    """SQLite-backed registry of killed strategies, their lessons, and the honest trial count."""

    def __init__(self, db_path: str = "data/research.db", tenure: int = DEFAULT_TENURE) -> None:
        self.db_path = db_path
        self.tenure = tenure
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
            # Every candidate ever scored. This is N for the deflated Sharpe, and it is
            # deliberately append-only: nothing is ever removed from the trial count.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trials (
                    trial_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    variant TEXT,
                    strategy_kind TEXT,
                    symbol TEXT,
                    period TEXT,
                    stage TEXT,
                    per_obs_sharpe REAL,
                    dsr REAL,
                    n_bars INTEGER,
                    created_ts REAL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_variant ON trials(variant)")
            # Columns added after the first release. SQLite has no IF NOT EXISTS for columns,
            # so probe and add. Existing rows keep NULLs, which read as "no variant recorded"
            # and therefore never match a hard tabu -- the safe direction.
            trial_cols = {r["name"] for r in conn.execute("PRAGMA table_info(trials)")}
            if "dsr" not in trial_cols:
                conn.execute("ALTER TABLE trials ADD COLUMN dsr REAL")
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(failures)")}
            for col, decl in (
                ("variant", "TEXT"),
                ("params_json", "TEXT"),
                ("period", "TEXT"),
                ("n_bars", "INTEGER"),
                ("trial_index", "INTEGER"),
            ):
                if col not in existing:
                    conn.execute(f"ALTER TABLE failures ADD COLUMN {col} {decl}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_variant ON failures(variant)")
            self._backfill_trials(conn)

    @staticmethod
    def _backfill_trials(conn: sqlite3.Connection) -> None:
        """Seed the trial count from historical tombstones, once.

        Those 18 failures were real trials and they belong in N. Without this the deflated
        Sharpe would restart from zero and understate how much has already been searched,
        which is the same class of error as the original bug. Runs only when `trials` is empty
        and `failures` is not, so it is idempotent and safe on the CI cache.
        """
        n_trials = conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        if n_trials:
            return
        rows = conn.execute(
            "SELECT strategy_kind, symbol, period, variant, created_ts FROM failures"
        ).fetchall()
        if not rows:
            return
        conn.executemany(
            """INSERT INTO trials (variant, strategy_kind, symbol, period, stage, created_ts)
               VALUES (?, ?, ?, ?, 'backfilled', ?)""",
            [(r["variant"], r["strategy_kind"], r["symbol"], r["period"], r["created_ts"])
             for r in rows],
        )

    # ------------------------------------------------------------------ writing

    def add(self, **fields) -> int:
        """Record a failure. `created_ts` may be passed in for determinism; defaults to now.

        Pass `params` and `period` so the tombstone identifies an exact variant. Without them
        the row is still stored for its lesson, but it can never impose a hard tabu, because
        we cannot tell which parameterisation died.
        """
        created_ts = fields.get("created_ts")
        if created_ts is None:
            created_ts = time.time()
        params = fields.get("params")
        kind = fields.get("strategy_kind")
        symbol = fields.get("symbol")
        period = fields.get("period")
        variant = (
            variant_hash(kind, params, symbol, period)
            if params is not None and kind and symbol and period
            else None
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO failures (
                    strategy_kind, symbol, killed_at_stage, cause_category,
                    plain_english, generalisable_lesson, proposing_agent, created_ts,
                    variant, params_json, period, n_bars, trial_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind, symbol,
                    fields.get("killed_at_stage"),
                    fields.get("cause_category"),
                    fields.get("plain_english"),
                    fields.get("generalisable_lesson"),
                    fields.get("proposing_agent"),
                    created_ts,
                    variant,
                    json.dumps(params, sort_keys=True, default=str) if params is not None else None,
                    period,
                    fields.get("n_bars"),
                    self.effective_n(),
                ),
            )
            return int(cur.lastrowid)

    def set_trial_dsr(self, trial_id: int, dsr: float) -> None:
        """Record the deflated Sharpe once multiple-testing correction has been applied.

        Kept on the trial row so "the best this engine has ever achieved" is answerable in
        the SAME units it is later compared against. Comparing a deflated Sharpe to a
        per-observation Sharpe made every cycle look like a record, which in turn credited
        every lesson every time and made the win rate meaningless.
        """
        with self._connect() as conn:
            conn.execute("UPDATE trials SET dsr=? WHERE trial_id=?", (float(dsr), trial_id))

    def best_dsr(self) -> float:
        """Best deflated Sharpe ever recorded. 0.0 when nothing has been scored yet."""
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(dsr) AS m FROM trials").fetchone()
        return float(row["m"] or 0.0)

    def record_trial(self, kind: str, params: dict | None, symbol: str, period: str,
                     stage: str, per_obs_sharpe: float | None = None,
                     n_bars: int | None = None, created_ts: float | None = None) -> int:
        """Count one candidate against N. Call this for EVERY candidate that reaches scoring,
        including tabu skips, because the deflation bar is a function of what was tried."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trials (variant, strategy_kind, symbol, period, stage,
                                    per_obs_sharpe, n_bars, created_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (variant_hash(kind, params, symbol, period), kind, symbol, period, stage,
                 per_obs_sharpe, n_bars, created_ts if created_ts is not None else time.time()),
            )
            return int(cur.lastrowid)

    # ------------------------------------------------------------------ reading

    def effective_n(self) -> int:
        """Total candidates ever scored. The honest N for the deflated Sharpe."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM trials").fetchone()
        return int(row["n"] or 0)

    def all(self) -> list[dict]:
        """Every recorded failure, oldest first."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM failures ORDER BY failure_id").fetchall()
        return [dict(r) for r in rows]

    def matches(self, kind: str, symbol: str, cause_category: str | None = None) -> list[dict]:
        """Prior failures with the same kind+symbol (and cause if given).

        RETAINED FOR REPORTING AND PROPOSER CONTEXT ONLY. Do not use this as a rejection
        test: keying a veto at family level is exactly the bug that stalled the loop for five
        weeks. Use `is_tabu` to decide whether to skip, and `family_penalty` to steer.
        """
        sql = "SELECT * FROM failures WHERE strategy_kind = ? AND symbol = ?"
        params: list = [kind, symbol]
        if cause_category is not None:
            sql += " AND cause_category = ?"
            params.append(cause_category)
        sql += " ORDER BY failure_id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def is_tabu(self, kind: str, params: dict | None, symbol: str, period: str,
                n_bars: int | None = None, aspiration: bool = False) -> tuple[bool, str]:
        """Should this EXACT variant be skipped? Returns (skip, reason).

        Hard tabu applies only to an identical re-run: same kind, same params, same symbol,
        same period. It lifts when either the tenure has elapsed (measured in trials since the
        failure) or enough new bars exist that the backtest could genuinely answer differently.
        `aspiration=True` overrides the tabu outright.
        """
        if aspiration:
            return False, "aspiration: predicted to beat the incumbent best"
        variant = variant_hash(kind, params, symbol, period)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM failures WHERE variant = ? ORDER BY failure_id DESC LIMIT 1",
                (variant,),
            ).fetchone()
        if row is None:
            return False, ""
        age = self.effective_n() - (row["trial_index"] or 0)
        if age >= self.tenure:
            return False, f"tabu expired after {age} trials"
        if n_bars and row["n_bars"] and n_bars >= row["n_bars"] * (1 + DATA_GROWTH_LIFT):
            return False, f"data grew {row['n_bars']} -> {n_bars} bars, retesting"
        return True, (f"exact variant already tested {age} trials ago "
                      f"({row['cause_category']})")

    def family_penalty(self, kind: str, symbol: str) -> float:
        """Soft frequency penalty in [0, 1) for a family that keeps failing here.

        This is a steer, not a gate. It is fed to the proposer as context and can be used to
        rank candidates. It never blocks a proposal.
        """
        n = len(self.matches(kind, symbol))
        return n / (n + 1.0)

    def summary(self) -> dict:
        """Counts of failures grouped by cause_category."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cause_category, COUNT(*) AS n FROM failures GROUP BY cause_category"
            ).fetchall()
        return {r["cause_category"]: int(r["n"]) for r in rows}
