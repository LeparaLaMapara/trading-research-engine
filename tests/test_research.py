"""Tests for the research/agent layer. Deterministic, offline (no API keys)."""
from __future__ import annotations

from council.backends import MockBackend, get_backend
from council.orchestrator import Council
from research.calibration import Calibration
from research.registry import FailureRegistry
from research.schemas import FalsifiablePrediction, StrategyProposal
from scout.scout import Scout

try:
    from strategy.registry import kinds_at_or_below
except Exception:  # pragma: no cover
    def kinds_at_or_below(rung: int) -> list[str]:
        rungs = {0: ["buy_hold", "random"], 2: ["ma_trend"], 3: ["vol_scaled"],
                 4: ["multi_timeframe"], 5: ["mean_reversion"]}
        out: list[str] = []
        for r in sorted(rungs):
            if r <= rung:
                out.extend(rungs[r])
        return out


def _db(tmp_path) -> str:
    return str(tmp_path / "research.db")


def test_failure_registry_add_all_matches(tmp_path):
    reg = FailureRegistry(db_path=_db(tmp_path))
    fid = reg.add(
        strategy_kind="ma_trend",
        symbol="EURUSD",
        killed_at_stage="backtest",
        cause_category="overfitting",
        plain_english="won in-sample, lost out-of-sample",
        generalisable_lesson="tune and judge on different data",
        proposing_agent="mock",
        created_ts=1000.0,
    )
    assert isinstance(fid, int) and fid > 0

    rows = reg.all()
    assert len(rows) == 1
    assert rows[0]["strategy_kind"] == "ma_trend"
    assert rows[0]["symbol"] == "EURUSD"

    # Same kind + symbol matches; a different symbol does not.
    assert len(reg.matches("ma_trend", "EURUSD")) == 1
    assert reg.matches("ma_trend", "GBPUSD") == []
    # Cause filter narrows correctly.
    assert len(reg.matches("ma_trend", "EURUSD", cause_category="overfitting")) == 1
    assert reg.matches("ma_trend", "EURUSD", cause_category="lookahead") == []

    assert reg.summary() == {"overfitting": 1}


def test_calibration_record_score(tmp_path):
    cal = Calibration(db_path=_db(tmp_path))
    pred = FalsifiablePrediction(
        prediction_id="p1",
        strategy_id="s1",
        agent="mock",
        committed_at="2026-08-06T00:00:00",
        sharpe_gt=0.5,          # actual 1.2 -> correct (obviously right)
        max_dd_lt=0.15,         # actual dd magnitude 0.50 -> incorrect (obviously wrong)
        win_rate_lo=0.40,
        win_rate_hi=0.60,       # actual 0.50 -> inside band (correct)
        trades_per_month_lo=1.0,
        trades_per_month_hi=10.0,  # actual 5 -> inside band (correct)
        confidence=0.6,
    )
    pid = cal.record(pred)
    assert isinstance(pid, int) and pid > 0

    actual = {
        "sharpe": 1.2,
        "max_drawdown": -0.50,  # sign-agnostic; magnitude 0.50 breaches 0.15 ceiling
        "win_rate": 0.50,
        "trades_per_month": 5.0,
    }
    result = cal.score(pid, actual)
    assert result["n_total"] > 0
    assert result["fields"]["sharpe_gt"] is True      # obviously correct
    assert result["fields"]["max_dd_lt"] is False     # obviously wrong
    assert result["n_correct"] == 3
    assert result["n_total"] == 4

    board = cal.agent_calibration("mock")
    assert board["n_predictions"] == 1
    assert 0.0 <= board["field_accuracy"] <= 1.0
    assert abs(board["field_accuracy"] - 0.75) < 1e-9
    assert abs(board["mean_confidence"] - 0.6) < 1e-9


def test_mockbackend_respects_max_rung_and_is_reproducible():
    allowed = set(kinds_at_or_below(2))
    backend = MockBackend(seed=7)

    for round_index in range(6):
        prop = backend.propose_json({"max_rung": 2, "round_index": round_index})
        assert prop["kind"] in allowed

    # Reproducible for the same (seed, round); different rounds may differ.
    a0 = MockBackend(seed=7).propose_json({"max_rung": 2, "round_index": 0})
    b0 = MockBackend(seed=7).propose_json({"max_rung": 2, "round_index": 0})
    assert a0 == b0
    a1 = MockBackend(seed=7).propose_json({"max_rung": 2, "round_index": 1})
    # Not required to differ, but the kind cycles across rounds for rung 2 (>1 allowed kind).
    assert a1["kind"] in allowed


def test_council_run_round_offline():
    council = Council()  # no keys -> mock backend
    context = {
        "symbol": "EURUSD",
        "period": "2020-2023",
        "max_rung": 3,
        "seen_failures": [],
    }
    out = council.run_round(context, round_index=0, committed_at="2026-08-06T00:00:00")

    prop = out["proposal"]
    assert isinstance(prop, StrategyProposal)
    assert prop.rung <= context["max_rung"]

    pred = out["prediction"]
    assert isinstance(pred, FalsifiablePrediction)
    assert pred.strategy_id == prop.id

    critique = out["critique"]
    assert "concerns" in critique and isinstance(critique["concerns"], list)
    assert critique["concerns"]
    # The Council never returns a trade verdict.
    assert "verdict" not in out
    assert "accept" not in out


def test_council_avoids_seen_failures():
    council = Council()
    context = {
        "symbol": "EURUSD",
        "period": "2020-2023",
        "max_rung": 2,
        "seen_failures": [{"strategy_kind": "ma_trend", "symbol": "EURUSD"}],
    }
    # ma_trend died; with max_rung 2 the proposer should avoid it where an alternative exists.
    out = council.run_round(context, round_index=1, committed_at="t")
    # buy_hold / random are still available at rung <= 2, so ma_trend should be avoidable.
    assert out["proposal"].kind != "ma_trend"


def test_scout_offline_no_fabricated_ids():
    scout = Scout()  # offline
    cards = scout.transfer_cards(n=3)
    assert len(cards) == 3
    for c in cards:
        assert c.identifier == "MOCK-OFFLINE"
        # No fabricated arXiv-looking identifier.
        assert "arxiv" not in c.identifier.lower()
        assert c.market_claim


def test_get_backend_offline_is_mock():
    backend = get_backend("mock")
    assert isinstance(backend, MockBackend)
