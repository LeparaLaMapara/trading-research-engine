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
