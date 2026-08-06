"""Dataclasses for the research/agent layer.

These are inert data containers. Nothing here decides whether to trade; they only carry
proposals, falsifiable predictions, and transfer cards between the agents and the store.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class StrategyProposal:
    """A proposed strategy spec. Proposed by an LLM, judged elsewhere by the backtest."""

    id: str
    kind: str
    params: dict
    rung: int
    symbol: str
    period: str
    agent: str
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FalsifiablePrediction:
    """A commitment made BEFORE the backtest runs, so an agent can be scored later (spec §4).

    `committed_at` is passed in by the caller (a timestamp string). We never call the clock
    inside this dataclass, so tests stay deterministic. `max_dd_lt` is a positive magnitude:
    the ceiling on drawdown depth (e.g. 0.15 means the drawdown must stay shallower than 15%).
    """

    prediction_id: str
    strategy_id: str
    agent: str
    committed_at: str
    sharpe_gt: float
    max_dd_lt: float
    win_rate_lo: float
    win_rate_hi: float
    trades_per_month_lo: float
    trades_per_month_hi: float
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TransferCard:
    """A cross-discipline idea imported by the Scout. `identifier` must be real or MOCK-OFFLINE.

    Anti-hallucination: never place a resolvable-looking arXiv id / DOI here unless it was
    actually fetched. Offline placeholders use identifier == "MOCK-OFFLINE".
    """

    id: str
    title: str
    identifier: str
    discipline: str
    market_claim: str
    assumptions_required: list[str] = field(default_factory=list)
    data_required: str = ""
    failure_regime: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
