"""The goal layer must be able to say no, and must say it in rands.

These lock the two properties that make the family-facing channel trustworthy: the verdict is
arithmetic (an LLM never decides it), and an impossible goal is reported as impossible rather
than accepted and quietly missed.
"""
from __future__ import annotations

from research.goals import (
    WORLD_CLASS_SHARPE,
    GoalSpec,
    assess,
    rebet_floor_zar,
    risk_per_trade_fraction,
    suggest_reachable,
)


def spec(target=2000.0, days=365, start=1000.0):
    return GoalSpec(author="sister", raw_text="I just want to make money",
                    target_zar=target, horizon_days=days, risk_zar=635.0, start_zar=start)


def test_floor_is_the_point_below_which_no_trade_is_possible():
    # Derived from the broker's real minimum: margin + one stop + stop-out buffer.
    assert 340 < rebet_floor_zar(18.0) < 400


def test_risk_per_trade_is_forced_by_lot_size_not_chosen():
    """The whole design turns on this: a smaller account cannot take smaller risk."""
    small = risk_per_trade_fraction(1000.0)
    large = risk_per_trade_fraction(10000.0)
    assert small > large
    assert small > 0.05      # R1000 cannot risk a conventional 1%
    assert large < small / 5


def test_doubling_in_three_months_is_refused():
    f = assess(spec(target=2000, days=90))
    assert f.feasible is False
    assert f.required_sharpe > WORLD_CLASS_SHARPE
    assert "no" in f.verdict_plain.lower()


def test_doubling_in_a_year_is_allowed_but_demanding():
    f = assess(spec(target=2000, days=365))
    assert f.feasible is True
    assert 0.5 < f.required_sharpe <= WORLD_CLASS_SHARPE


def test_longer_horizon_never_makes_a_goal_harder():
    sharpes = [assess(spec(days=d)).required_sharpe for d in (90, 365, 1095)]
    assert sharpes == sorted(sharpes, reverse=True)


def test_verdict_is_written_in_rands_not_jargon():
    v = assess(spec()).verdict_plain
    assert "R1,000" in v and "R2,000" in v
    for jargon in ("deflated", "p-value", "walk-forward", "drawdown", "alpha"):
        assert jargon not in v.lower()


def test_account_below_the_floor_is_told_plainly():
    f = assess(spec(start=180.0, target=400.0))
    assert f.feasible is False
    assert "floor" in f.verdict_plain.lower()


def test_below_floor_does_not_offer_a_deadline():
    """Time is not the blocker below the floor; suggesting one would mislead."""
    alts = suggest_reachable(spec(start=180.0, target=400.0))
    assert "days_needed_at_world_class_skill" not in alts
    assert alts["funding_for_1pct_risk_zar"] > 0


def test_target_at_or_below_start_is_not_treated_as_growth():
    f = assess(spec(target=800.0, start=1000.0))
    assert f.feasible is False
    # And the probability sentence must not appear: it would be arithmetic about nothing.
    assert "chance of reaching" not in f.context_plain


def test_probabilities_are_complementary_and_bounded():
    f = assess(spec())
    assert 0.0 <= f.prob_reach_target_no_edge <= 1.0
    assert abs(f.prob_reach_target_no_edge + f.prob_hit_floor_no_edge - 1.0) < 1e-6
