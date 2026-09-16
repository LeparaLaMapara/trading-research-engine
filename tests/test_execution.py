"""Sizing and the risk gate: the half of the pipeline that did not exist until today.

Until 2026-09-16 `RiskOfficer.permit()` was called in exactly one place and that place was a
test, nothing sized a position, and nothing managed one. A candidate could pass the hardest
gate in the project and the path ended in a print statement.

The properties locked here are refusals, because on a small account the correct answer is
usually no trade, and because every refusal that fails open is a live order nobody intended.
"""
from __future__ import annotations

import pytest

from execution.sizing import SymbolSpec, size_position, stop_and_target
from risk.limits import DEMO_REHEARSAL_LIMITS, LIVE_LIMITS, Limits, RiskOfficer

EURUSD = SymbolSpec("EURUSD", min_volume=100000, step_volume=100000,
                    max_volume=1000000000, lot_size=10000000, pip_size=0.0001, digits=5)


# ------------------------------------------------------------------ sizing


def test_refuses_when_the_smallest_position_exceeds_the_risk_limit():
    """The real situation on the live account: R540 at 1:50 risks ~10% per minimum trade.

    The correct answer is no trade, NOT a quietly raised limit.
    """
    s = size_position(equity=30.0, risk_fraction=0.02, stop_pips=30.0, spec=EURUSD,
                      margin_per_min_volume=23.09)
    assert s.allowed is False
    assert s.volume == 0
    assert "smallest position" in s.reason


def test_never_rounds_up_past_the_limit():
    """Rounding up would silently exceed the limit the calculation exists to hold."""
    for equity in (1000, 2500, 5000, 20000, 100000):
        s = size_position(equity, 0.02, 30.0, EURUSD, margin_per_min_volume=23.09)
        if s.allowed:
            assert s.risk_fraction_actual <= 0.02 + 1e-9, equity


def test_size_scales_with_equity():
    small = size_position(5000, 0.02, 30.0, EURUSD, margin_per_min_volume=23.09)
    big = size_position(100000, 0.02, 30.0, EURUSD, margin_per_min_volume=23.09)
    assert big.volume > small.volume


def test_a_position_without_a_stop_cannot_be_sized():
    s = size_position(100000, 0.02, 0.0, EURUSD)
    assert s.allowed is False
    assert "stop" in s.reason


def test_refuses_when_margin_exceeds_equity():
    s = size_position(100.0, 0.5, 5.0, EURUSD, margin_per_min_volume=500.0)
    assert s.allowed is False


def test_refuses_when_no_room_to_absorb_the_stop():
    """Enough to OPEN is not enough to HOLD: a forced close before the stop is worse than
    no trade at all."""
    s = size_position(equity=25.0, risk_fraction=0.9, stop_pips=30.0, spec=EURUSD,
                      margin_per_min_volume=23.0)
    assert s.allowed is False


def test_stop_and_target_sit_the_right_side_of_the_entry():
    sl, tp = stop_and_target(1.15421, "BUY", 30.0, EURUSD, reward_ratio=1.5)
    assert sl < 1.15421 < tp
    sl, tp = stop_and_target(1.15421, "SELL", 30.0, EURUSD, reward_ratio=1.5)
    assert tp < 1.15421 < sl


# ------------------------------------------------------------------ the risk gate


def _ok(**over):
    base = dict(account_environment="demo", equity=500000.0, risk_amount=5000.0,
                margin_required=50000.0, open_positions=0, realised_pnl_today=0.0,
                equity_peak=500000.0)
    base.update(over)
    return base


def test_unconfigured_limits_deny():
    """Forgetting to configure the risk layer must fail CLOSED."""
    assert RiskOfficer().permit(**_ok()).allowed is False


def test_live_limits_are_not_configured_and_therefore_deny():
    """The whole safety story for the live account. If this test ever fails, someone has
    filled in the section 1 numbers and that must be a deliberate, signed-off act."""
    assert LIVE_LIMITS.configured() is False
    d = RiskOfficer(LIVE_LIMITS).permit(**_ok(account_environment="live"))
    assert d.allowed is False


def test_demo_limits_refuse_a_live_account():
    """Environment is part of the limits, so a rehearsal cannot leak onto the live account."""
    d = RiskOfficer(DEMO_REHEARSAL_LIMITS).permit(**_ok(account_environment="live"))
    assert d.allowed is False
    assert "live" in d.reason


def test_unknown_environment_denies():
    d = RiskOfficer(DEMO_REHEARSAL_LIMITS).permit(**_ok(account_environment=None))
    assert d.allowed is False


@pytest.mark.parametrize("over,expect", [
    ({"risk_amount": 50000.0}, "risks"),
    ({"open_positions": 1}, "already open"),
    ({"margin_required": 400000.0}, "margin"),
    ({"realised_pnl_today": -30000.0}, "today"),
    ({"equity_peak": 700000.0}, "drawdown"),
    ({"equity": 500.0, "risk_amount": 5.0}, "floor"),
])
def test_each_limit_denies_independently(over, expect):
    d = RiskOfficer(DEMO_REHEARSAL_LIMITS).permit(**_ok(**over))
    assert d.allowed is False
    assert expect in d.reason


def test_a_valid_demo_order_is_allowed():
    """The gate must be able to say yes, or it is not a gate, it is a wall."""
    assert RiskOfficer(DEMO_REHEARSAL_LIMITS).permit(**_ok()).allowed is True


def test_missing_information_is_a_refusal_not_an_assumption():
    d = RiskOfficer(DEMO_REHEARSAL_LIMITS).permit(**_ok(equity=None))
    assert d.allowed is False
