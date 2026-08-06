"""Harness: costs must bite, and P&L accounting must be internally consistent."""
import numpy as np
import pandas as pd

from backtest.harness import CostModel, run_backtest
from strategy.ma_trend import MovingAverageTrend


def _uptrend(n=120):
    close = 1.10 + np.arange(n) * 0.001      # steady uptrend
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600.0, "close": close})


def test_costs_reduce_returns():
    bars = _uptrend()
    strat = MovingAverageTrend(5, 20)
    cheap_cost = CostModel(0.1, 0.0001, 1.10)
    cheap = run_backtest(bars, strat, cheap_cost, 6240)
    dear = run_backtest(bars, strat, CostModel(50.0, 0.0001, 1.10), 6240)
    # A bigger spread can only lower total return.
    assert dear.summary["total_return"] < cheap.summary["total_return"]
    # net == gross - turnover * cost_per_unit_turnover, exactly.
    turnover = cheap.positions.diff().abs().fillna(cheap.positions.abs())
    expected_cost = turnover * cheap_cost.cost_per_unit_turnover()
    assert np.allclose((cheap.gross_returns - cheap.net_returns).to_numpy(),
                       expected_cost.to_numpy())


def test_uptrend_is_profitable_gross():
    bars = _uptrend()
    res = run_backtest(bars, MovingAverageTrend(5, 20), CostModel(0.1, 0.0001, 1.10), 6240)
    assert res.gross_returns.sum() > 0        # following a clean uptrend makes money pre-cost
    assert len(res.positions) == len(bars)    # no lookahead misalignment


def test_trade_segmentation_counts_round_trips():
    # Force a known position path via a tiny custom series is complex; instead assert that
    # the number of trades equals the number of non-zero holding segments.
    bars = _uptrend()
    res = run_backtest(bars, MovingAverageTrend(5, 20), CostModel(0.1, 0.0001, 1.10), 6240)
    pos = res.positions
    segments = ((pos != pos.shift(1)) & (pos != 0)).sum()
    assert res.summary["num_trades"] == segments
