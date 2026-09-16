"""The cost ceiling: deleting a rule for being too expensive, before it is ever scored.

The property that matters is ORDER. Charging a cost inside the backtest lets an expensive
rule compete and lets the optimiser recover the drag from a lucky fold. Rejecting it up
front does not. These tests lock the arithmetic and the refusals; the one on `unknown is
not rejected` is the same discipline the walk-forward already follows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.harness import CostModel
from research.cost_ceiling import (COST_CEILING_SR, MIN_PROBE_BARS, cost_in_sharpe_units,
                                   probe_cost)
from strategy.base import Strategy

CHEAP = CostModel(spread_pips=0.2, pip_size=0.0001, ref_price=1.10)
DEAR = CostModel(spread_pips=40.0, pip_size=0.0001, ref_price=1.10)


def _bars(n=600, seed=1):
    close = 1.10 + np.cumsum(np.random.default_rng(seed).normal(0, 0.001, n))
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600.0, "close": close})


class _Flip(Strategy):
    """Alternates every bar. The most expensive rule that can exist at this resolution."""
    name = "flip"

    def generate_signals(self, bars):
        return pd.Series(np.where(np.arange(len(bars)) % 2 == 0, 1.0, -1.0), dtype=float)

    def economic_rationale(self):
        return "none; it exists to cost money"


class _Hold(Strategy):
    """Buys once and never trades again. Turnover is one bar's worth over the whole run."""
    name = "hold"

    def generate_signals(self, bars):
        return pd.Series(np.ones(len(bars)), dtype=float)

    def economic_rationale(self):
        return "long the instrument"


class _Flat(Strategy):
    name = "flat"

    def generate_signals(self, bars):
        return pd.Series(np.zeros(len(bars)), dtype=float)

    def economic_rationale(self):
        return "never trades"


# ------------------------------------------------------------------ the arithmetic


def test_cost_in_sharpe_units_scales_with_turnover():
    bars = _bars()
    ret = bars["close"].pct_change().fillna(0.0)
    flip = _Flip().generate_signals(bars)
    hold = _Hold().generate_signals(bars)
    flip_sr, flip_t, _, _ = cost_in_sharpe_units(flip, ret, CHEAP, "H1")
    hold_sr, hold_t, _, _ = cost_in_sharpe_units(hold, ret, CHEAP, "H1")
    assert flip_t > hold_t
    assert flip_sr > hold_sr


def test_cost_in_sharpe_units_scales_with_the_spread():
    bars = _bars()
    ret = bars["close"].pct_change().fillna(0.0)
    sig = _Flip().generate_signals(bars)
    cheap, *_ = cost_in_sharpe_units(sig, ret, CHEAP, "H1")
    dear, *_ = cost_in_sharpe_units(sig, ret, DEAR, "H1")
    assert dear > cheap


def test_a_rule_that_takes_no_risk_has_no_finite_cost_ratio():
    """Zero volatility in the denominator. Must not silently divide by zero."""
    bars = _bars()
    ret = bars["close"].pct_change().fillna(0.0)
    sr, *_ = cost_in_sharpe_units(pd.Series(np.zeros(len(bars))), ret, CHEAP, "H1")
    assert sr == float("inf")


# ------------------------------------------------------------------ the gate


def test_the_flip_rule_is_rejected():
    est = probe_cost(_bars(), _Flip, CHEAP, "H1")
    assert est.evaluable is True
    assert est.affordable is False
    assert "ceiling" in est.reason


def test_the_hold_rule_is_affordable():
    est = probe_cost(_bars(), _Hold, CHEAP, "H1")
    assert est.evaluable is True
    assert est.affordable is True
    assert est.cost_sr <= COST_CEILING_SR


def test_the_same_rule_can_be_affordable_cheap_and_rejected_dear():
    """Cost is a property of the rule AND the instrument, never of the rule alone."""
    cheap = probe_cost(_bars(), _Flip, CostModel(0.01, 0.0001, 1.10), "H1")
    dear = probe_cost(_bars(), _Flip, DEAR, "H1")
    assert dear.affordable is False
    assert dear.cost_sr > cheap.cost_sr


def test_a_raised_ceiling_admits_more():
    bars = _bars()
    strict = probe_cost(bars, _Flip, CHEAP, "H1", ceiling_sr=0.01)
    loose = probe_cost(bars, _Flip, CHEAP, "H1", ceiling_sr=1e9)
    assert strict.affordable is False
    assert loose.affordable is True


# ------------------------------------------------------------------ unknown is not failed


def test_too_little_history_is_not_a_rejection():
    est = probe_cost(_bars(MIN_PROBE_BARS - 1), _Flip, DEAR, "H1")
    assert est.evaluable is False
    assert est.affordable is True          # unknown must not be reported as too expensive


def test_a_rule_that_never_takes_a_position_is_not_evaluable():
    est = probe_cost(_bars(), _Flat, DEAR, "H1")
    assert est.evaluable is False
    assert "never takes a position" in est.reason


def test_a_rule_that_raises_is_not_a_cost_rejection():
    class _Broken(Strategy):
        name = "broken"

        def generate_signals(self, bars):
            raise RuntimeError("boom")

        def economic_rationale(self):
            return "n/a"

    est = probe_cost(_bars(), _Broken, CHEAP, "H1")
    assert est.evaluable is False
    assert "boom" in est.reason


def test_the_probe_only_sees_the_training_portion():
    """Lookahead here could only cause a wrong rejection, but it should still not happen."""
    seen: list[int] = []

    class _Spy(Strategy):
        name = "spy"

        def generate_signals(self, bars):
            seen.append(len(bars))
            return pd.Series(np.ones(len(bars)), dtype=float)

        def economic_rationale(self):
            return "n/a"

    bars = _bars(600)
    probe_cost(bars, _Spy, CHEAP, "H1", train_fraction=0.5)
    assert seen and max(seen) <= 300
