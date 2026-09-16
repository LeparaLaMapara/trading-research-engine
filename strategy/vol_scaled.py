"""Complexity-ladder rung 3: a trend rule sized inversely to recent volatility.

Direction is the moving-average crossover sign (as in MovingAverageTrend). Size targets a
constant risk budget: target_vol / recent realized volatility, clipped to a leverage cap.
Everything is shifted one bar so the position held during bar t uses only closes up to t-1.

**Units, which were wrong until 2026-09-16.** `target_vol` is an ANNUAL volatility target,
but it was being divided by a PER-BAR standard deviation. On D1 EURUSD that is 0.10 / 0.005
= 20, clipped to the leverage cap of 1.0 -- on every bar, without exception. The rule
therefore reduced to plain MovingAverageTrend and the universe sweep was scoring the same
model twice under two names, inflating the trial count that the deflated Sharpe depends on.
The tell was bit-identical Sharpes on all four symbols tested.

The volatility is now annualised before the comparison, using the bar spacing inferred from
the data rather than a period string, so the same rule is correct at any frequency.
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
        # ANNUALISED realized volatility, so it is comparable with an annual target.
        per_bar_vol = close.pct_change().rolling(self.vol_window).std()
        realized_vol = per_bar_vol * np.sqrt(self._bars_per_year(bars))
        leverage = self.target_vol / realized_vol.replace(0.0, np.nan)
        leverage = leverage.clip(upper=self.max_leverage)
        raw = (direction * leverage).clip(-self.max_leverage, self.max_leverage)
        raw = raw.fillna(0.0)
        # Decide from data through the PREVIOUS bar: shift by one. No lookahead.
        return raw.shift(1).fillna(0.0)

    @staticmethod
    def _bars_per_year(bars: pd.DataFrame) -> float:
        """Infer bars per year from the median timestamp gap.

        Markets are not open 365 days, so the convention here is the project's: 260 trading
        days a year. A daily gap of 86,400s gives 260, an hourly gap gives 6,240, and both
        match backtest.metrics.BARS_PER_YEAR. Inferring beats taking a period string because
        the strategy is constructed by name from a proposal that need not carry one.
        """
        ts = bars.get("ts_utc")
        if ts is None or len(ts) < 3:
            return 260.0
        dt = float(pd.Series(ts).diff().median() or 0.0)
        if dt <= 0:
            return 260.0
        return max(1.0, 260.0 * 86400.0 / dt)

    def economic_rationale(self) -> str:
        return ("Sizing inversely to volatility is the single biggest risk-adjusted "
                "improvement over a raw trend rule: it holds risk-per-trade steady, taking "
                "more size when the market is calm and less when it is turbulent.")
