"""Complexity-ladder rung 4: a trend rule blended across several lookbacks.

For each window take the sign of price minus its rolling mean, then average those signs.
The result is a position in [-1, 1] that scales with agreement across horizons. Shifted one
bar so the position held during bar t uses only closes up to t-1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import Strategy


class MultiTimeframeTrend(Strategy):
    def __init__(self, windows: tuple[int, ...] = (50, 100, 200)) -> None:
        if not windows:
            raise ValueError("windows must be non-empty")
        self.windows = tuple(windows)
        self.name = f"multi-tf{self.windows}"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        signs = []
        for w in self.windows:
            signs.append(np.sign(close - close.rolling(w).mean()))
        raw = pd.concat(signs, axis=1).mean(axis=1)
        raw = raw.fillna(0.0)
        # Decide from data through the PREVIOUS bar: shift by one. No lookahead.
        return raw.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("Blending trend signals from several lookbacks reduces fragility to any one "
                "horizon: a rule tuned to a single window is brittle, while agreement across "
                "windows is a steadier, harder-to-fit signal.")
