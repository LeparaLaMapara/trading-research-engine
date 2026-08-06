"""Complexity-ladder rung 0: the benchmarks every real strategy must beat.

BuyHold is the trivial always-long baseline. RandomEntry is the null model: a coin
flip per bar, deterministic from (seed, bar index) so it is reproducible and free of
lookahead. Most strategies fail to beat one or both of these once costs are charged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import Strategy


class BuyHold(Strategy):
    def __init__(self) -> None:
        self.name = "buy-hold"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        # Always long. Shifted for interface consistency; the value never changes.
        raw = pd.Series(1.0, index=bars.index, dtype=float)
        return raw.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("The baseline every strategy must beat after costs: if an active rule cannot "
                "outperform simply holding the asset, it is adding cost and risk for nothing.")


class RandomEntry(Strategy):
    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.name = f"random({seed})"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        # Position per bar derived only from (seed, integer bar index): the i-th draw is
        # fixed by the seed and does not depend on how many bars follow, so truncating the
        # data leaves earlier signals unchanged. No price is read, so there is no lookahead.
        n = len(bars)
        rng = np.random.default_rng(self.seed)
        picks = rng.integers(0, 2, size=n) * 2 - 1  # {0,1} -> {-1,+1}
        raw = pd.Series(picks.astype(float), index=bars.index)
        return raw.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("The null benchmark: entries are coin flips with no information. Most "
                "strategies fail to beat random after costs, which is exactly the point.")
