"""Complexity-ladder registry: which strategy kinds live on which rung, and a factory.

The ladder (spec §9) is simplest-first: a strategy is only promoted over a simpler one if it
wins out-of-sample after costs. This module names the rungs and builds strategies by kind so
callers never import the classes directly.
"""
from __future__ import annotations

import inspect

from strategy.base import Strategy
from strategy.benchmark import BuyHold, RandomEntry
from strategy.ma_trend import MovingAverageTrend
from strategy.mean_reversion import MeanReversion
from strategy.multi_timeframe import MultiTimeframeTrend
from strategy.kalman_level import KalmanLevel
from strategy.ou_reversion import OUReversion
from strategy.vol_scaled import VolScaledTrend

# Rung -> the strategy kinds that sit at that complexity level.
RUNGS: dict[int, list[str]] = {
    0: ["buy_hold", "random"],
    2: ["ma_trend"],
    3: ["vol_scaled"],
    4: ["multi_timeframe"],
    5: ["mean_reversion"],
    # Rung 6 is where parameters start being ESTIMATED from data rather than chosen by a
    # human. Everything here implements FittedStrategy, and the experiment loop must score it
    # with walk_forward_refit: scoring a fitted model without refitting shows it its own
    # training data and reports a number that means nothing.
    6: ["ou_reversion"],
    # Rung 7: state-space models. The quantity traded is a LATENT variable inferred from
    # noisy observations, and the model reports its own uncertainty. Built on TFiltersPy.
    7: ["kalman_level"],
}

_BUILDERS = {
    "buy_hold": BuyHold,
    "random": RandomEntry,
    "ma_trend": MovingAverageTrend,
    "vol_scaled": VolScaledTrend,
    "multi_timeframe": MultiTimeframeTrend,
    "mean_reversion": MeanReversion,
    "ou_reversion": OUReversion,
    "kalman_level": KalmanLevel,
}


def rung_of(kind: str) -> int:
    """Return the ladder rung a strategy kind belongs to."""
    for rung, kinds in RUNGS.items():
        if kind in kinds:
            return rung
    raise ValueError(f"unknown strategy kind: {kind}")


def kinds_at_or_below(rung: int) -> list[str]:
    """All strategy kinds on rungs up to and including `rung`, low rung first."""
    out: list[str] = []
    for r in sorted(RUNGS):
        if r <= rung:
            out.extend(RUNGS[r])
    return out


def build_strategy(kind: str, params: dict) -> Strategy:
    """Construct a strategy by kind. Only params matching the constructor are passed, so a
    real LLM proposal carrying extra or differently-named keys degrades to the defaults
    instead of crashing (e.g. Gemini's 'fast_window' is dropped; 'fast' is used)."""
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"unknown strategy kind: {kind}")
    accepted = set(inspect.signature(builder).parameters)
    clean = {k: v for k, v in (params or {}).items() if k in accepted}
    return builder(**clean)
