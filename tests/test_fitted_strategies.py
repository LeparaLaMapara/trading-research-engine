"""The rung where parameters are estimated, and the lookahead that comes with it.

Fitting is the point where a backtest can start lying convincingly. A model shown its own
training data produces a beautiful number that means nothing, so these tests lock the
separation between fitting and predicting rather than the performance of any one model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import walkforward as wf
from backtest.harness import CostModel
from strategy.base import FittedStrategy
from strategy.ou_reversion import OUReversion
from strategy.registry import build_strategy, rung_of


def ou_series(n=40000, theta=0.08, mu=1.15, sigma=0.0004, seed=1) -> pd.DataFrame:
    """A market that genuinely mean-reverts, so we know the right answer exists."""
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = x[t - 1] + theta * (mu - x[t - 1]) + sigma * rng.standard_normal()
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600, "close": x})


def trending(n=2000, seed=2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600,
                         "close": 100 + np.arange(n) * 0.01 + rng.standard_normal(n) * 0.1})


COSTS = CostModel(spread_pips=0.1, pip_size=0.0001, commission_per_side=0.0, ref_price=1.15)


# ------------------------------------------------------------------ the contract


def test_an_unfitted_model_never_trades():
    """The most important safety property on this rung."""
    bars = ou_series(2000)
    assert (OUReversion().generate_signals(bars) == 0).all()


def test_fitting_recovers_parameters_it_was_never_told():
    true_theta, true_mu = 0.08, 1.15
    p = OUReversion().fit(ou_series()).fitted_params
    assert p["tradable"]
    assert abs(p["theta"] - true_theta) < 0.02
    assert abs(p["mu"] - true_mu) < 0.01
    assert abs(p["half_life_bars"] - np.log(2) / true_theta) < 2.0


def test_the_model_chooses_its_own_horizon():
    """The half-life is the model's statement about horizon, not a human's guess."""
    fast = OUReversion().fit(ou_series(theta=0.20, seed=3)).fitted_params
    slow = OUReversion().fit(ou_series(theta=0.02, seed=3)).fitted_params
    assert fast["half_life_bars"] < slow["half_life_bars"]
    assert fast["window"] < slow["window"]


def test_it_refuses_rather_than_inverting_into_a_trend_follower():
    """No mean reversion present must mean NO TRADE, not the opposite trade. Flipping sign
    would be a different hypothesis wearing this one's clothes."""
    m = OUReversion().fit(trending())
    assert m.fitted_params["tradable"] is False
    assert (m.generate_signals(trending()) == 0).all()


def test_it_is_registered_above_the_heuristic_rungs():
    assert rung_of("ou_reversion") > rung_of("mean_reversion")
    assert isinstance(build_strategy("ou_reversion", {}), FittedStrategy)


# ------------------------------------------------------------------ the harness


def test_refit_harness_finds_a_real_edge_when_one_exists():
    """If the honest harness cannot find signal in a series built to contain it, the harness
    is broken and every negative result it produces is worthless."""
    r = wf.walk_forward_refit(ou_series(), lambda: OUReversion(), COSTS, "H1")
    assert r["evaluable"]
    assert r["dev_summary"]["sharpe"] > 1.0
    assert r["holdout_summary"]["sharpe"] > 1.0


def test_each_fold_is_fitted_separately():
    r = wf.walk_forward_refit(ou_series(), lambda: OUReversion(), COSTS, "H1")
    fitted = [p for p in r["fold_params"] if p and p.get("tradable")]
    assert len(fitted) >= 2
    # Stability across folds is the diagnostic: wildly different estimates mean the model is
    # chasing noise, not measuring a property of the market.
    hl = [p["half_life_bars"] for p in fitted]
    assert max(hl) / min(hl) < 3.0


class _WindowHungry(FittedStrategy):
    """A stub that always asks for a lookback wider than any test fold.

    Testing the harness with a controlled stub rather than a real model: OU's own estimates
    move around between folds, so a test built on them checks the estimator as much as the
    harness, and fails for the wrong reasons.
    """

    def __init__(self, window: int = 100000) -> None:
        self.window = window
        self.name = "window_hungry"
        self.fitted_params = None

    def fit(self, train_bars):
        self.fitted_params = {"window": self.window}
        return self

    def generate_signals(self, bars):
        # Needs `window` bars of history before it can say anything, so on a shorter fold it
        # holds no position at all.
        return (bars["close"].rolling(self.window, min_periods=self.window)
                .mean().notna().astype(float).shift(1).fillna(0.0))

    def economic_rationale(self) -> str:
        return "test stub"


def test_a_model_that_never_trades_is_not_evaluable_rather_than_zero():
    """A Sharpe of 0.0 from a model that never opened a position is not a result.

    This is the exact trap the real EURUSD sample fell into: the fitted lookback needed more
    history than each test window provided, so nothing was exercised and the naive report was
    a clean, meaningless zero.
    """
    r = wf.walk_forward_refit(ou_series(n=5000), lambda: _WindowHungry(), COSTS, "H1")
    assert r["evaluable"] is False
    assert r["dev_summary"] is None
    assert "history" in r["why_not"]
    assert all(a == 0 for a in r["fold_active_bars"])


def test_partial_coverage_is_visible():
    """A model scored on only some folds must not look like one scored on all of them."""
    r = wf.walk_forward_refit(ou_series(), lambda: OUReversion(), COSTS, "H1")
    assert r["folds_evaluated"] <= r["folds_attempted"]
    assert r["folds_attempted"] > 0


def test_fresh_instance_per_fold():
    """A reused object can carry state from a later period backwards, which is lookahead no
    amount of careful indexing catches."""
    seen = []

    def factory():
        s = OUReversion()
        seen.append(id(s))
        return s

    wf.walk_forward_refit(ou_series(), factory, COSTS, "H1")
    assert len(seen) == len(set(seen)), "a strategy instance was reused across folds"


def test_non_fitted_strategies_still_use_the_plain_harness():
    """Rung 6 must not break the rungs below it."""
    bars = ou_series(3000)
    r = wf.walk_forward(bars, build_strategy("ma_trend", {}), COSTS, "H1")
    assert r["dev_summary"] is not None


# ------------------------------------------------- rung 7: state-space (TFiltersPy)


def local_level(n=20000, q_ratio=1e-3, r_sd=0.0005, seed=3) -> pd.DataFrame:
    """Price as a noisy observation of a latent level that wanders. The model's own world."""
    r = np.random.default_rng(seed)
    lvl = np.cumsum(r.standard_normal(n) * np.sqrt(q_ratio * r_sd ** 2)) + 1.15
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600, "close": lvl + r.standard_normal(n) * r_sd})


def test_kalman_recovers_the_signal_to_noise_ratio():
    """R is profiled against each candidate ratio. Estimating R once from the one-bar changes
    double-counts the process noise (var(diff) = Q + 2R) and biased the ratio ~3x low."""
    from strategy.kalman_level import KalmanLevel
    for q_true in (1e-4, 1e-2):
        p = KalmanLevel().fit(local_level(4000, q_ratio=q_true, seed=1)).fitted_params
        assert p["tradable"]
        assert 0.3 < p["q_over_r"] / q_true < 3.0


def test_kalman_is_above_the_ou_rung_and_is_fitted():
    from strategy.kalman_level import KalmanLevel
    assert rung_of("kalman_level") > rung_of("ou_reversion")
    assert isinstance(build_strategy("kalman_level", {}), FittedStrategy)
    assert (KalmanLevel().generate_signals(local_level(500)) == 0).all()


def test_kalman_finds_a_latent_level_when_one_exists():
    from strategy.kalman_level import KalmanLevel
    r = wf.walk_forward_refit(local_level(), lambda: KalmanLevel(), COSTS, "H1")
    assert r["evaluable"] and r["dev_summary"]["sharpe"] > 1.0


def test_kalman_parameter_estimates_are_stable_across_folds():
    """Unstable estimates mean noise-chasing. Identical ones mean a measured property."""
    from strategy.kalman_level import KalmanLevel
    r = wf.walk_forward_refit(local_level(), lambda: KalmanLevel(), COSTS, "H1")
    qs = [p["q_over_r"] for p in r["fold_params"] if p and p.get("tradable")]
    assert len(qs) >= 2 and max(qs) / min(qs) < 3.0


def test_kalman_finds_nothing_in_a_random_walk():
    """The discrimination test. A model that scores well on a driftless random walk after
    costs is reporting lookahead, not skill."""
    from strategy.kalman_level import KalmanLevel
    r = np.random.default_rng(7)
    n = 20000
    walk = pd.DataFrame({"ts_utc": np.arange(n) * 3600,
                         "close": 1.15 + np.cumsum(r.standard_normal(n) * 0.0005)})
    res = wf.walk_forward_refit(walk, lambda: KalmanLevel(), COSTS, "H1")
    if res["evaluable"]:
        assert res["dev_summary"]["sharpe"] < 2.0
