"""Metric correctness on known inputs."""
import numpy as np
import pandas as pd

from backtest import metrics


def test_max_drawdown_known():
    # equity 1 -> 1.2 -> 0.9 : peak 1.2, trough 0.9 -> dd = 0.9/1.2 - 1 = -0.25
    returns = pd.Series([0.2, -0.25])
    assert round(metrics.max_drawdown(returns), 4) == -0.25


def test_sharpe_zero_for_constant_returns():
    assert metrics.sharpe(pd.Series([0.01, 0.01, 0.01]), 252) == 0.0


def test_summarize_win_rate_and_trades():
    net = pd.Series([0.01, -0.02, 0.03])
    trades = [0.05, -0.01, 0.02, 0.04]
    s = metrics.summarize(net, trades, 252)
    assert s["num_trades"] == 4
    assert s["win_rate"] == 0.75      # 3 of 4 positive
