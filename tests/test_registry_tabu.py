"""Regression tests for the failure-memory rules and the spend cap.

The bug these exist to prevent: the registry keyed rejection on (strategy_kind, symbol),
which meant one failure permanently banned an entire strategy family on that symbol. After
18 failures the complete 6-kinds x 3-symbols cross product was blacklisted and the daily run
tested nothing for five weeks while reporting success.
"""
from __future__ import annotations

import pytest

from council.budget import BudgetExceeded, BudgetGuard, price_of
from research.registry import FailureRegistry, variant_hash


@pytest.fixture()
def reg(tmp_path):
    return FailureRegistry(str(tmp_path / "research.db"), tenure=10)


def _fail(reg, kind="ma_trend", params=None, symbol="EURUSD", period="H1", n_bars=3000):
    reg.add(strategy_kind=kind, symbol=symbol, period=period, params=params or {"w": 20},
            killed_at_stage="backtest", cause_category="failed_deflated_sharpe",
            plain_english="x", generalisable_lesson="y", proposing_agent="test", n_bars=n_bars)
    reg.record_trial(kind, params or {"w": 20}, symbol, period, stage="backtest")


def test_variant_hash_is_order_insensitive():
    a = variant_hash("ma_trend", {"fast": 10, "slow": 50}, "EURUSD", "H1")
    b = variant_hash("ma_trend", {"slow": 50, "fast": 10}, "EURUSD", "H1")
    assert a == b


def test_variant_hash_separates_different_params():
    a = variant_hash("ma_trend", {"fast": 10}, "EURUSD", "H1")
    b = variant_hash("ma_trend", {"fast": 11}, "EURUSD", "H1")
    assert a != b


def test_same_family_different_params_is_not_blocked(reg):
    """THE regression. One failure must not ban the family."""
    _fail(reg, params={"w": 20})
    skip, _ = reg.is_tabu("ma_trend", {"w": 50}, "EURUSD", "H1", n_bars=3000)
    assert skip is False


def test_exact_repeat_is_skipped(reg):
    _fail(reg, params={"w": 20})
    skip, why = reg.is_tabu("ma_trend", {"w": 20}, "EURUSD", "H1", n_bars=3000)
    assert skip is True
    assert "exact variant" in why


def test_tabu_expires_after_tenure(reg):
    _fail(reg, params={"w": 20})
    for i in range(reg.tenure + 1):
        reg.record_trial("other", {"i": i}, "EURUSD", "H1", stage="backtest")
    skip, why = reg.is_tabu("ma_trend", {"w": 20}, "EURUSD", "H1", n_bars=3000)
    assert skip is False
    assert "expired" in why


def test_aspiration_overrides_tabu(reg):
    _fail(reg, params={"w": 20})
    skip, why = reg.is_tabu("ma_trend", {"w": 20}, "EURUSD", "H1", n_bars=3000, aspiration=True)
    assert skip is False
    assert "aspiration" in why


def test_data_growth_lifts_tabu(reg):
    _fail(reg, params={"w": 20}, n_bars=3000)
    skip, why = reg.is_tabu("ma_trend", {"w": 20}, "EURUSD", "H1", n_bars=3600)
    assert skip is False
    assert "data grew" in why


def test_legacy_rows_without_params_cannot_veto(reg):
    """Tombstones written before parameters were recorded must never block anything."""
    reg.add(strategy_kind="ma_trend", symbol="EURUSD", killed_at_stage="backtest",
            cause_category="failed_deflated_sharpe", plain_english="x",
            generalisable_lesson="y", proposing_agent="legacy")
    skip, _ = reg.is_tabu("ma_trend", {"w": 20}, "EURUSD", "H1", n_bars=3000)
    assert skip is False


def test_family_penalty_grows_but_never_reaches_one(reg):
    assert reg.family_penalty("ma_trend", "EURUSD") == 0.0
    for w in (10, 20, 30):
        _fail(reg, params={"w": w})
    p = reg.family_penalty("ma_trend", "EURUSD")
    assert 0.0 < p < 1.0


def test_effective_n_counts_every_trial_including_skips(reg):
    """N for the deflated Sharpe must count what was TRIED, not what was reported."""
    assert reg.effective_n() == 0
    _fail(reg, params={"w": 20})
    reg.record_trial("ma_trend", {"w": 20}, "EURUSD", "H1", stage="tabu")
    reg.record_trial("mean_reversion", {"w": 5}, "EURUSD", "H1", stage="spec")
    assert reg.effective_n() == 3


# ----------------------------------------------------------------- budget guard


def test_unknown_model_prices_at_worst_known_rate():
    """Under-estimating costs money; over-estimating only stops the run early."""
    worst = max(price_of(m) for m in ("claude-fable-5-1", "claude-opus-5"))
    assert price_of("some-model-we-have-never-seen") == worst


def test_guard_blocks_before_the_call_not_after():
    g = BudgetGuard(max_usd=0.01, max_calls=100)
    with pytest.raises(BudgetExceeded):
        g.check("claude-opus-5", "s" * 4000, "u" * 40000, 4096)
    assert g.calls == 0
    assert g.spent_usd == 0.0


def test_guard_enforces_call_cap():
    g = BudgetGuard(max_usd=1000.0, max_calls=2)
    for _ in range(2):
        g.check("claude-opus-5", "s", "u", 10)
        g.record("claude-opus-5", 10, 10)
    with pytest.raises(BudgetExceeded, match="call cap"):
        g.check("claude-opus-5", "s", "u", 10)
