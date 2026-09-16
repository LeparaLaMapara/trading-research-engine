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


# ---------------------------------------------------------------- vol scaling units


def test_vol_scaled_is_not_just_a_trend_rule_in_disguise():
    """Regression, 2026-09-16: an ANNUAL target_vol was divided by a PER-BAR std.

    On D1 EURUSD that is 0.10 / 0.005 = 20, clipped to the 1.0 leverage cap on every bar,
    so the rule collapsed to MovingAverageTrend and the universe sweep scored one model
    twice under two names. The tell was bit-identical Sharpes across four symbols.
    """
    import numpy as np
    import pandas as pd

    from strategy.ma_trend import MovingAverageTrend
    from strategy.vol_scaled import VolScaledTrend

    rng = np.random.default_rng(0)
    n = 1200
    # Deliberately regime-switching volatility: a vol-scaled rule MUST react to this.
    vol = np.where(np.arange(n) % 400 < 200, 0.002, 0.02)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
    bars = pd.DataFrame({"ts_utc": np.arange(n) * 86400.0, "close": close})

    trend = MovingAverageTrend(20, 50).generate_signals(bars)
    scaled = VolScaledTrend(20, 50).generate_signals(bars)

    assert not np.array_equal(trend.to_numpy(), scaled.to_numpy())
    # It must take genuinely intermediate sizes, not just -1/0/+1.
    assert len(np.unique(np.round(scaled.to_numpy(), 3))) > 10
    # And it must size DOWN in the turbulent regime relative to the calm one.
    calm = scaled[(np.arange(n) % 400) < 200].abs().mean()
    rough = scaled[(np.arange(n) % 400) >= 200].abs().mean()
    assert rough < calm


def test_vol_scaled_infers_the_same_bars_per_year_as_the_metrics_table():
    """The annualisation must agree with backtest.metrics, or the units drift apart again."""
    import numpy as np
    import pandas as pd

    import pytest

    from backtest.metrics import BARS_PER_YEAR
    from strategy.vol_scaled import VolScaledTrend

    for period, dt in (("D1", 86400.0), ("H1", 3600.0), ("H4", 14400.0)):
        bars = pd.DataFrame({"ts_utc": np.arange(50) * dt, "close": np.ones(50)})
        assert VolScaledTrend._bars_per_year(bars) == pytest.approx(
            BARS_PER_YEAR[period], rel=1e-9), period
