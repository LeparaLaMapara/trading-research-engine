"""Complexity-ladder rung 3: a trend rule sized inversely to recent volatility.

Direction is the moving-average crossover sign (as in MovingAverageTrend). Size targets a
constant risk budget: target_vol / recent realized volatility, clipped to a leverage cap.
Everything is shifted one bar so the position held during bar t uses only closes up to t-1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import Strategy


class VolScaledTrend(Strategy):
    def __init__(self, fast: int = 20, slow: int = 50, vol_window: int = 20,
                 target_vol: float = 0.10, max_leverage: float = 1.0) -> None:
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast = fast
        self.slow = slow
        self.vol_window = vol_window
        self.target_vol = target_vol
        self.max_leverage = max_leverage
        self.name = f"vol-scaled({fast}/{slow},tv={target_vol})"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        direction = pd.Series(0.0, index=bars.index, dtype=float)
        direction[fast_ma > slow_ma] = 1.0
        direction[fast_ma < slow_ma] = -1.0
        # Per-bar realized volatility: rolling std of returns over vol_window (consistent units).
        realized_vol = close.pct_change().rolling(self.vol_window).std()
        leverage = self.target_vol / realized_vol.replace(0.0, np.nan)
        leverage = leverage.clip(upper=self.max_leverage)
        raw = (direction * leverage).clip(-self.max_leverage, self.max_leverage)
        raw = raw.fillna(0.0)
        # Decide from data through the PREVIOUS bar: shift by one. No lookahead.
        return raw.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("Sizing inversely to volatility is the single biggest risk-adjusted "
                "improvement over a raw trend rule: it holds risk-per-trade steady, taking "
                "more size when the market is calm and less when it is turbulent.")
