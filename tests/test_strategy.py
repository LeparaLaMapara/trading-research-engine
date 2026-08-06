"""The strategy must be free of lookahead — the property everything else trusts."""
import numpy as np
import pandas as pd
import pytest

from strategy.ma_trend import MovingAverageTrend


def _bars(n=120, seed=1):
    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(rng.normal(0, 0.001, n))
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600.0, "close": close})


def test_no_lookahead_truncation_invariance():
    strat = MovingAverageTrend(5, 20)
    bars = _bars()
    full = strat.generate_signals(bars)
    # Signals for the first k bars must not change when later bars are removed.
    for k in (40, 80, 119):
        trunc = strat.generate_signals(bars.iloc[:k])
        assert np.allclose(full.iloc[:k].to_numpy(), trunc.to_numpy())


def test_signal_is_shifted_and_bounded():
    strat = MovingAverageTrend(5, 20)
    sig = strat.generate_signals(_bars())
    assert sig.iloc[0] == 0.0                     # shifted: first bar has no position
    assert set(np.unique(sig)).issubset({-1.0, 0.0, 1.0})


def test_fast_must_be_shorter_than_slow():
    with pytest.raises(ValueError):
        MovingAverageTrend(50, 20)
