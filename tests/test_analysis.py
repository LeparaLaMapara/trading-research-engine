"""Analysis package: assumption tests, regime tagging, session filter.

Synthetic data only, no DB required for the core tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from analysis.assumptions import adf_test, hurst_exponent
from analysis.regime import tag_regimes
from analysis.session_filter import SessionFilter

_SAST = ZoneInfo("Africa/Johannesburg")


# --- assumptions ---------------------------------------------------------------

def test_adf_distinguishes_stationary_from_random_walk():
    rng = np.random.default_rng(0)
    noise = rng.normal(size=2000)
    white_noise = pd.Series(noise)
    random_walk = pd.Series(np.cumsum(noise))
    assert adf_test(white_noise)["stationary"] is True
    assert adf_test(random_walk)["stationary"] is False


def test_hurst_orders_random_walk_above_mean_reverting():
    rng = np.random.default_rng(1)
    random_walk = pd.Series(np.cumsum(rng.normal(size=4000)))
    # A hard sign-flipping series is strongly mean-reverting.
    mean_reverting = pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(4000)])
    assert hurst_exponent(random_walk) >= 0.4
    assert hurst_exponent(mean_reverting) < 0.5


# --- regime --------------------------------------------------------------------

def test_tag_regimes_adds_columns_and_valid_labels():
    rng = np.random.default_rng(2)
    close = 1.10 + np.cumsum(rng.normal(scale=0.001, size=300))
    bars = pd.DataFrame({"ts_utc": np.arange(300) * 3600.0, "close": close})
    tagged = tag_regimes(bars, vol_window=20, trend_window=50)
    for col in ("realized_vol", "vol_regime", "trend_regime"):
        assert col in tagged.columns
    labels = set(tagged["vol_regime"].dropna().unique())
    assert labels.issubset({"low", "med", "high"})
    assert set(tagged["trend_regime"].dropna().unique()).issubset({"trending", "ranging"})
    assert len(tagged) == len(bars)


# --- session filter ------------------------------------------------------------

def _epoch(dt_sast: datetime) -> float:
    return dt_sast.replace(tzinfo=_SAST).astimezone(timezone.utc).timestamp()


def test_session_filter_masks_outside_allowed_hours():
    # Monday 2024-01-01 in SAST. 10:00 -> hour_of_week 10; 15:00 -> hour_of_week 15.
    inside = _epoch(datetime(2024, 1, 1, 10, 0))   # allowed
    outside = _epoch(datetime(2024, 1, 1, 15, 0))  # not allowed
    bars = pd.DataFrame({"ts_utc": [inside, outside], "close": [1.0, 1.0]})
    positions = pd.Series([1.0, 1.0], index=bars.index)

    sf = SessionFilter(allowed_hours_of_week={10})
    masked = sf.apply(bars, positions)

    assert masked.iloc[0] == 1.0   # inside allowed hour, unchanged
    assert masked.iloc[1] == 0.0   # outside allowed hour, zeroed
