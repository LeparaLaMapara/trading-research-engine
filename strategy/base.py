"""Strategy interface.

A strategy maps bars -> a target position series in {-1, 0, +1}, using ONLY past data.
The no-lookahead rule is the strategy's responsibility: the position to HOLD during bar t
must be decided from information available at the CLOSE of bar t-1 or earlier. Concretely,
compute your signal then `.shift(1)` before returning it.

`economic_rationale()` is mandatory (spec §3.5): if a strategy cannot state in plain
English why it should work economically, that is a red flag for curve-fitted noise.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str = "unnamed"

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Return target position per bar (index-aligned to `bars`), values in {-1,0,1}.
        MUST be free of lookahead — shift signals so bar t uses only data <= t-1."""

    @abstractmethod
    def economic_rationale(self) -> str:
        """One plain-English sentence: why should this make money?"""


class FittedStrategy(Strategy):
    """A strategy whose parameters are ESTIMATED from data rather than chosen by a human.

    This is the rung where the project stops hand-picking a lookback and starts letting the
    data choose. It is also where lookahead becomes the dominant risk, so the contract is
    deliberately strict and the backtest enforces it:

        fit(train_bars)          may look at every row of train_bars and nothing else
        generate_signals(bars)   may use only the parameters learned in fit(), plus the
                                 no-lookahead rule every strategy already obeys

    A fitted strategy tested WITHOUT refitting per window is not being tested, it is being
    shown its own answers. `backtest.walkforward.walk_forward_refit` exists for that reason
    and is the only honest way to score anything on this rung or above.

    Everything above this rung (classical ML, state-space and volatility models, and anything
    physics-informed or self-supervised later) implements this same two-method contract, so
    the gate, the cost model and the deflation apply to all of them unchanged.
    """

    #: Set by fit(). Nothing may be inferred from data before this is populated.
    fitted_params: dict | None = None

    @abstractmethod
    def fit(self, train_bars: pd.DataFrame) -> "FittedStrategy":
        """Estimate parameters from `train_bars` ONLY. Return self."""

    def is_fitted(self) -> bool:
        return self.fitted_params is not None
