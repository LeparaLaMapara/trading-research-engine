"""Falsifiable-prediction scoring and agent calibration (spec §4).

An agent commits bounds before the backtest runs; later we score those bounds against the
actual measured result and keep a running scoreboard. The scoreboard is the number the
non-expert owner reads to decide which agent to trust. This module scores predictions;
it never decides whether to trade.
"""
from __future__ import annotations

import json
import os
import sqlite3

from research.schemas import FalsifiablePrediction


class Calibration:
    """SQLite-backed prediction ledger and per-agent accuracy scoreboard."""

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
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT,
                    agent TEXT,
                    committed_at TEXT,
                    payload TEXT,
                    scored INTEGER DEFAULT 0,
                    correct_fields TEXT,
                    n_correct INTEGER,
                    n_total INTEGER
                )
                """
            )

    def record(self, prediction: FalsifiablePrediction) -> int:
        """Store a prediction (payload as json). Returns the row id."""
        payload = json.dumps(prediction.to_dict())
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO predictions (strategy_id, agent, committed_at, payload, scored)
                VALUES (?, ?, ?, ?, 0)
                """,
                (
                    prediction.strategy_id,
                    prediction.agent,
                    prediction.committed_at,
                    payload,
                ),
            )
            return int(cur.lastrowid)

    def score(self, prediction_id: int, actual: dict) -> dict:
        """Compare committed bounds to the actual measured result and store the outcome.

        `actual` has keys: sharpe, max_drawdown (sign-agnostic; we compare magnitude),
        win_rate, trades_per_month. Each committed bound becomes one correct/incorrect field.
        Returns the per-field result.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM predictions WHERE prediction_id = ?",
                (prediction_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"no prediction with id {prediction_id}")
            p = json.loads(row["payload"])

            fields: dict[str, bool] = {}

            # Sharpe must exceed the committed floor.
            fields["sharpe_gt"] = float(actual["sharpe"]) > float(p["sharpe_gt"])

            # Drawdown magnitude must stay below the committed ceiling.
            actual_dd = abs(float(actual["max_drawdown"]))
            fields["max_dd_lt"] = actual_dd < float(p["max_dd_lt"])

            # Win rate must land inside the committed band.
            wr = float(actual["win_rate"])
            fields["win_rate_band"] = (
                float(p["win_rate_lo"]) <= wr <= float(p["win_rate_hi"])
            )

            # Trades per month must land inside the committed band.
            tpm = float(actual["trades_per_month"])
            fields["trades_per_month_band"] = (
                float(p["trades_per_month_lo"]) <= tpm <= float(p["trades_per_month_hi"])
            )

            n_total = len(fields)
            n_correct = sum(1 for v in fields.values() if v)

            conn.execute(
                """
                UPDATE predictions
                SET scored = 1, correct_fields = ?, n_correct = ?, n_total = ?
                WHERE prediction_id = ?
                """,
                (json.dumps(fields), n_correct, n_total, prediction_id),
            )

        return {
            "prediction_id": prediction_id,
            "fields": fields,
            "n_correct": n_correct,
            "n_total": n_total,
        }

    def agent_calibration(self, agent: str) -> dict:
        """Scoreboard for one agent over its scored predictions.

        Returns n_predictions, field_accuracy (overall correct fields / total fields), and
        mean_confidence (average committed confidence across the scored predictions).
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload, n_correct, n_total
                FROM predictions
                WHERE agent = ? AND scored = 1
                """,
                (agent,),
            ).fetchall()

        n_predictions = len(rows)
        total_correct = sum(int(r["n_correct"] or 0) for r in rows)
        total_fields = sum(int(r["n_total"] or 0) for r in rows)
        field_accuracy = (total_correct / total_fields) if total_fields else 0.0

        confidences = []
        for r in rows:
            try:
                confidences.append(float(json.loads(r["payload"]).get("confidence", 0.0)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        mean_confidence = (sum(confidences) / len(confidences)) if confidences else 0.0

        return {
            "n_predictions": n_predictions,
            "field_accuracy": field_accuracy,
            "mean_confidence": mean_confidence,
        }
