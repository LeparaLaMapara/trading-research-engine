"""Complexity-ladder rung 5: a z-score mean-reversion rule with a hysteresis band.

Fade stretched moves: short when price is far above its rolling mean, long when far below,
and flatten only once it has reverted inside an inner band. Between the bands the previous
position is held. Everything is shifted one bar so bar t uses only closes up to t-1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import Strategy


class MeanReversion(Strategy):
    def __init__(self, window: int = 20, z_entry: float = 1.5, z_exit: float = 0.5) -> None:
        if z_exit >= z_entry:
            raise ValueError("z_exit must be smaller than z_entry")
        self.window = window
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.name = f"mean-rev({window},{z_entry}/{z_exit})"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        mean = close.rolling(self.window).mean()
        std = close.rolling(self.window).std()
        z = (close - mean) / std.replace(0.0, np.nan)
        # NaN encodes "hold the previous position"; concrete values set/flatten it.
        raw = pd.Series(np.nan, index=bars.index, dtype=float)
        raw[z > self.z_entry] = -1.0          # fade the spike up
        raw[z < -self.z_entry] = 1.0          # fade the spike down
        raw[z.abs() < self.z_exit] = 0.0      # reverted: flatten
        # Carry forward past state only (causal), then start flat.
        raw = raw.ffill().fillna(0.0)
        # Decide from data through the PREVIOUS bar: shift by one. No lookahead.
        return raw.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("In ranging regimes prices revert to a local mean, so fading moves that have "
                "stretched far from it captures the snap back. It loses in strong trends, when "
                "the stretch keeps stretching.")
