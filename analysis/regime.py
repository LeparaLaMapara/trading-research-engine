"""Regime tagging (spec section 6): break results out by volatility and trend/range.

A strategy that only works in high-volatility trends is not the same instrument as one that
works everywhere. Tagging bars by regime lets the backtest report performance per regime
instead of hiding it in one blended number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _kaufman_efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    """Kaufman efficiency ratio: net move over gross path, in [0, 1].

    ER = |close - close.shift(w)| / rolling_sum(|close.diff()|). Near 1 means a clean
    directional move (trending); near 0 means lots of motion with little progress (ranging).
    """
    net = (close - close.shift(window)).abs()
    gross = close.diff().abs().rolling(window).sum()
    er = net / gross.replace(0.0, np.nan)
    return er


def tag_regimes(bars: pd.DataFrame, vol_window: int = 20, trend_window: int = 50) -> pd.DataFrame:
    """Return a copy of bars with realized_vol, vol_regime and trend_regime columns.

    - realized_vol: rolling std of close pct_change over vol_window.
    - vol_regime: {"low","med","high"} by terciles of realized_vol.
    - trend_regime: {"trending","ranging"} via Kaufman efficiency ratio over trend_window,
      split at the median ER (high ER = trending).

    Leading rows without enough history carry NaN in realized_vol / ER and therefore an
    unset (NaN) regime, which is honest rather than guessed.
    """
    out = bars.copy()

    rets = out["close"].pct_change()
    out["realized_vol"] = rets.rolling(vol_window).std()

    vol = out["realized_vol"]
    vol_regime = pd.Series(np.nan, index=out.index, dtype="object")
    if vol.notna().sum() >= 3:
        try:
            binned = pd.qcut(vol, 3, labels=["low", "med", "high"], duplicates="drop")
            vol_regime = binned.astype("object").where(binned.notna(), np.nan)
        except ValueError:
            vol_regime = vol.notna().map({True: "med"}).where(vol.notna(), np.nan)
    else:
        vol_regime = vol.notna().map({True: "med"}).where(vol.notna(), np.nan)
    out["vol_regime"] = vol_regime

    er = _kaufman_efficiency_ratio(out["close"], trend_window)
    out["efficiency_ratio"] = er
    threshold = er.median(skipna=True)
    trend_regime = pd.Series(np.nan, index=out.index, dtype="object")
    trend_regime[er >= threshold] = "trending"
    trend_regime[er < threshold] = "ranging"
    out["trend_regime"] = trend_regime

    return out
