"""Extended strategy suite: no-lookahead, bounds, reproducibility, registry, validator.

The one property everything downstream trusts is no lookahead. We prove it the same way as
the core suite: truncation invariance — signals on the first k bars must not change when the
later bars are removed.
"""
import numpy as np
import pandas as pd

from strategy.benchmark import BuyHold, RandomEntry
from strategy.vol_scaled import VolScaledTrend
from strategy.mean_reversion import MeanReversion
from strategy.multi_timeframe import MultiTimeframeTrend
from strategy import registry
from strategy.validator import validate_proposal


def _bars(n=200, seed=7):
    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(rng.normal(0, 0.001, n))
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600.0, "close": close})


def _strategies():
    return [
        BuyHold(),
        RandomEntry(seed=1),
        VolScaledTrend(fast=10, slow=30, vol_window=15),
        MeanReversion(window=20),
        MultiTimeframeTrend(windows=(20, 50, 100)),
    ]


def test_no_lookahead_truncation_invariance():
    bars = _bars()
    for strat in _strategies():
        full = strat.generate_signals(bars)
        for k in (80, 150):
            trunc = strat.generate_signals(bars.iloc[:k])
            assert np.allclose(full.iloc[:k].to_numpy(), trunc.to_numpy()), strat.name


def test_positions_within_bounds():
    bars = _bars()
    for strat in _strategies():
        sig = strat.generate_signals(bars)
        assert sig.min() >= -1.0 - 1e-9, strat.name
        assert sig.max() <= 1.0 + 1e-9, strat.name


def test_random_entry_reproducible():
    bars = _bars()
    a = RandomEntry(seed=3).generate_signals(bars)
    b = RandomEntry(seed=3).generate_signals(bars)
    assert np.allclose(a.to_numpy(), b.to_numpy())


def test_validator_rejects_martingale():
    assert validate_proposal({"kind": "martingale", "params": {}})[0] is False


def test_validator_accepts_clean_proposal():
    assert validate_proposal({"kind": "ma_trend", "params": {"fast": 10, "slow": 30}})[0] is True


def test_registry_build_and_rung():
    strat = registry.build_strategy("mean_reversion", {"window": 10})
    assert isinstance(strat, MeanReversion)
    assert registry.rung_of("vol_scaled") == 3
