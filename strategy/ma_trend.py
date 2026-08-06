"""Complexity-ladder rung 2: a single moving-average trend rule. Boring on purpose.

Long when the fast MA is above the slow MA, short when below. The signal is shifted one
bar so the position held during bar t depends only on closes up to t-1 (no lookahead).
"""
from __future__ import annotations

import pandas as pd

from strategy.base import Strategy


class MovingAverageTrend(Strategy):
    def __init__(self, fast: int = 20, slow: int = 50, allow_short: bool = True) -> None:
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast = fast
        self.slow = slow
        self.allow_short = allow_short
        self.name = f"MA-trend({fast}/{slow})"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        raw = pd.Series(0, index=bars.index, dtype=float)
        raw[fast_ma > slow_ma] = 1.0
        raw[fast_ma < slow_ma] = -1.0 if self.allow_short else 0.0
        # Decide from data through the PREVIOUS bar: shift by one. No lookahead.
        return raw.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("Prices trend: once a move is underway it tends to persist, so following the "
                "prevailing direction captures the middle of sustained moves. It pays for that "
                "edge with losses in choppy, ranging markets.")
