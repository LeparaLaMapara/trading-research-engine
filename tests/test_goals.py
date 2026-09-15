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


def test_floor_tracks_the_account_leverage():
    """The floor is margin + one stop + stop-out buffer, and margin depends on leverage.

    This was hardcoded at 1:100 until the cTrader grant screen showed the funded account is
    1:50, which doubles the margin and moves the floor from R364 to R675. Leverage is read
    from config now, and must eventually be read from the broker (leverageInCents).
    """
    from research.goals import MIN_LOT_MARGIN_USD
    floor = rebet_floor_zar(18.0)
    assert floor > MIN_LOT_MARGIN_USD * 18.0     # always above the bare margin
    assert 600 < floor < 760                     # at the real 1:50


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


def test_doubling_in_a_year_needs_a_stake_that_survives_the_attempt():
    """At R1000 the skill needed is reachable, but the ruin risk is not acceptable.

    This is the flaw that shipped once: `feasible` looked only at required Sharpe, so the
    model called a 10%-per-trade plan the EASIEST one, because risking more lowers the
    Sharpe you need while raising the chance of never trading again.
    """
    thin = assess(spec(target=2000, days=365, start=1000.0))
    assert thin.required_sharpe <= WORLD_CLASS_SHARPE   # the skill is reachable
    assert thin.feasible is False                       # but the attempt probably ruins it
    assert thin.prob_hit_floor_no_edge > 0.35

    funded = assess(spec(target=3000, days=365, start=1500.0))
    assert funded.feasible is True


def test_longer_horizon_never_makes_a_goal_harder():
    sharpes = [assess(spec(days=d)).required_sharpe for d in (90, 365, 1095)]
    assert sharpes == sorted(sharpes, reverse=True)


def test_verdict_is_written_in_rands_not_jargon():
    v = assess(spec()).verdict_plain
    assert "R1,000" in v and "R2,000" in v
    for jargon in ("deflated", "p-value", "walk-forward", "drawdown", "alpha"):
        assert jargon not in v.lower()


def test_below_bare_margin_says_it_cannot_open_a_trade_at_all():
    f = assess(spec(start=180.0, target=400.0))
    assert f.feasible is False
    assert "just to open" in f.verdict_plain


def test_between_margin_and_floor_says_it_cannot_survive_the_trade():
    """The distinction that matters: enough to OPEN a position is not enough to HOLD one.

    Conflating the two told the owner he could not trade at all when the real problem was
    that one trade would tie up most of the account as margin.
    """
    f = assess(spec(start=540.0, target=1080.0))
    assert f.feasible is False
    assert "tie up" in f.verdict_plain and "room to breathe" in f.verdict_plain


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


def test_probabilities_are_bounded_and_need_not_sum_to_one():
    """Within a finite horizon a path can touch neither barrier, so they do NOT sum to 1.

    The earlier closed form implied they must, which is what made a well-funded account read
    as 94% ruined: it was answering "ever", not "within the year".
    """
    f = assess(spec())
    assert 0.0 <= f.prob_reach_target_no_edge <= 1.0
    assert 0.0 <= f.prob_hit_floor_no_edge <= 1.0
    assert f.prob_reach_target_no_edge + f.prob_hit_floor_no_edge <= 1.0 + 1e-9


def test_risking_more_can_never_make_a_goal_look_easier():
    """The property the flaw violated. A thinner stake means more risk per trade, which
    lowers the required Sharpe; it must not therefore read as more achievable."""
    thin = assess(spec(target=1600.0, days=365, start=800.0))
    fat = assess(spec(target=4000.0, days=365, start=2000.0))
    assert thin.required_sharpe < fat.required_sharpe     # thin "looks" easier on skill
    assert thin.prob_hit_floor_no_edge > fat.prob_hit_floor_no_edge
    assert thin.feasible is False and fat.feasible is True


def test_the_simulation_is_reproducible():
    a = assess(spec(target=1080.0, days=365, start=540.0))
    b = assess(spec(target=1080.0, days=365, start=540.0))
    assert a.prob_hit_floor_no_edge == b.prob_hit_floor_no_edge
