"""Walk-forward split + the multiple-testing correction (deflated Sharpe)."""
import numpy as np
import pandas as pd

from backtest.harness import CostModel
from backtest import walkforward as wf
from strategy.ma_trend import MovingAverageTrend


def _returns(mean, n=500, seed=0):
    return pd.Series(np.random.default_rng(seed).normal(mean, 0.01, n))


def test_psr_higher_for_better_returns():
    good = wf.probabilistic_sharpe_ratio(_returns(0.002))
    flat = wf.probabilistic_sharpe_ratio(_returns(0.0))
    assert good > flat
    assert good > 0.5


def test_deflated_sharpe_penalises_more_trials():
    r = _returns(0.002)
    few = wf.deflated_sharpe_ratio(r, n_trials=2, sharpe_std_across_trials=0.1)
    many = wf.deflated_sharpe_ratio(r, n_trials=500, sharpe_std_across_trials=0.1)
    assert many <= few          # more things tried -> higher bar -> lower confidence


def test_expected_max_sharpe_grows_with_trials():
    assert wf.expected_max_sharpe(0.1, 500) > wf.expected_max_sharpe(0.1, 10)


def test_walk_forward_shape():
    n = 800
    close = 1.10 + np.cumsum(np.random.default_rng(1).normal(0, 0.001, n))
    bars = pd.DataFrame({"ts_utc": np.arange(n) * 3600.0, "close": close})
    out = wf.walk_forward(bars, MovingAverageTrend(10, 30), CostModel(0.2, 0.0001, 1.10),
                          "H1", n_splits=4)
    assert "split_sharpes" in out and "dev_summary" in out
    assert out["holdout_summary"] is not None
    assert isinstance(out["dev_net_returns"], pd.Series)
