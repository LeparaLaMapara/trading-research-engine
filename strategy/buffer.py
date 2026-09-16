"""No-trade buffers: the cheapest turnover reduction available.

A raw signal in {-1, 0, +1} flips on every marginal change of mind. Each flip pays the
spread. Across 27 evaluable model-instrument pairs in this project, exactly ONE was
positive on both dev and holdout where chance alone predicts about seven, which is the
signature of costs eating a signal that had little edge to begin with. The first thing to
try against that is not a better signal. It is fewer trades.

**Carver's buffer.** Put a dead zone of width `buffer` around the position you already
hold. While the new target sits inside that zone, do nothing. When it leaves, move only as
far as the near EDGE of the zone, not all the way to the target:

    |target - current| <= buffer   ->  hold current
    otherwise                      ->  move to target - buffer * sign(target - current)

Moving to the edge rather than the target is what makes this work. Moving all the way
would re-arm the same flip next bar, so the buffer would delay churn instead of removing
it. Two consequences worth stating plainly:

  * Positions become FRACTIONAL. A {-1,0,1} signal through a 0.5 buffer produces a path
    through +/-0.5. The backtest handles continuous positions natively; live, the sizing
    module rounds down to the broker's volume step and is allowed to answer "no trade".
  * The buffer is CAUSAL. It reads the current and past target only, so it cannot
    introduce lookahead into a signal that did not already have it.

**Minimum holding period** is the blunter alternative for rules that should not be
fractional at all: take the position, then keep it for k bars whatever the signal says.
It is a worse tool in general (it ignores how strong the disagreement is) but it is the
honest one when a position has a fixed lifetime for an economic reason.

Neither is free. A buffer trades responsiveness for cost, so it helps a rule whose edge
decays slowly and hurts one whose edge is genuinely short-lived. That is an empirical
question per rule, which is why `buffer` is a parameter the search can vary rather than a
constant someone chose.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import Strategy

#: A sensible starting buffer for a {-1,0,1} signal: halves the step size of every move.
DEFAULT_BUFFER = 0.5


def apply_buffer(target: pd.Series, buffer: float = DEFAULT_BUFFER) -> pd.Series:
    """Carver's no-trade buffer applied to a target-position series.

    Returns the position actually HELD each bar, index-aligned to `target`.
    """
    if buffer <= 0:
        return target.astype(float).fillna(0.0)

    tgt = target.astype(float).fillna(0.0).to_numpy()
    held = np.empty_like(tgt)
    current = 0.0
    for i in range(len(tgt)):
        gap = tgt[i] - current
        if abs(gap) > buffer:
            # Move to the near edge of the dead zone, not to the target.
            current = tgt[i] - buffer * np.sign(gap)
        held[i] = current
    return pd.Series(held, index=target.index, name=getattr(target, "name", None))


def min_holding_period(target: pd.Series, bars: int) -> pd.Series:
    """Hold any non-zero position for at least `bars` bars before changing it.

    A flat target does not reset the clock early: the whole point is that the position has
    a minimum lifetime. Going flat is a change like any other and waits its turn.
    """
    if bars <= 1:
        return target.astype(float).fillna(0.0)

    tgt = target.astype(float).fillna(0.0).to_numpy()
    held = np.empty_like(tgt)
    current = 0.0
    age = 0
    for i in range(len(tgt)):
        if current != 0.0 and age < bars:
            age += 1                      # locked: ride the existing position
        elif tgt[i] != current:
            current = tgt[i]
            age = 1 if current != 0.0 else 0
        held[i] = current
    return pd.Series(held, index=target.index, name=getattr(target, "name", None))


def turnover_of(positions: pd.Series) -> float:
    """Mean |delta position| per bar. The thing a buffer exists to reduce."""
    p = positions.astype(float).fillna(0.0)
    return float(p.diff().abs().fillna(p.abs()).mean())


class Buffered(Strategy):
    """Wrap any strategy in a no-trade buffer, a minimum holding period, or both.

    Composes with `_SessionWrapped` in the research loop and with everything on the
    complexity ladder, because it only ever transforms the signal series.
    """

    def __init__(self, inner: Strategy, buffer: float = DEFAULT_BUFFER,
                 min_hold_bars: int = 0) -> None:
        self.inner = inner
        self.buffer = float(buffer)
        self.min_hold_bars = int(min_hold_bars)
        bits = []
        if self.buffer > 0:
            bits.append(f"buf{self.buffer:g}")
        if self.min_hold_bars > 1:
            bits.append(f"hold{self.min_hold_bars}")
        self.name = f"{inner.name}+{'+'.join(bits)}" if bits else inner.name

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        sig = self.inner.generate_signals(bars)
        if self.buffer > 0:
            sig = apply_buffer(sig, self.buffer)
        if self.min_hold_bars > 1:
            sig = min_holding_period(sig, self.min_hold_bars)
        return sig

    def economic_rationale(self) -> str:
        return (f"{self.inner.economic_rationale()} Trades are suppressed while the signal "
                f"change is smaller than the cost of acting on it.")
