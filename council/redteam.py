"""The Red Team agent: tries to refute a proposal.

It is ADVISORY only. `recommend_kill` is a suggestion for humans and the pipeline to weigh;
the backtest harness, not this agent, actually decides a strategy's fate.
"""
from __future__ import annotations

import json

from council.backends import STANDARD_CONCERNS, MockBackend
from research.schemas import StrategyProposal

_SYSTEM_PROMPT = (
    "You are a red-team reviewer of a proposed trading strategy. Your job is to REFUTE it: "
    "find lookahead, overfitting, regime dependence, cost/slippage blindness, or a missing "
    "economic rationale. You do NOT decide whether to trade; the backtest does. "
    "Respond with STRICT JSON: "
    '{"concerns": [str, ...], "recommend_kill": bool}. No prose outside the JSON.'
)


class RedTeam:
    """Critiques a StrategyProposal without deciding its fate."""

    def __init__(self, backend) -> None:
        self.backend = backend

    def critique(self, proposal: StrategyProposal) -> dict:
        """Return {"concerns": [...], "recommend_kill": bool}.

        Mock returns the standard checklist and recommend_kill=False (advisory only). Real
        backends are prompted to try to refute; on parse failure it falls back to the checklist.
        """
        if isinstance(self.backend, MockBackend):
            result = self.backend.critique_json(proposal)
            return {
                "concerns": result.get("concerns", list(STANDARD_CONCERNS)),
                "recommend_kill": False,
            }

        user = (
            f"Proposal: kind={proposal.kind} params={proposal.params} "
            f"symbol={proposal.symbol} period={proposal.period} rung={proposal.rung}. "
            f"Rationale: {proposal.rationale}. Try to refute it."
        )
        try:
            text = self.backend.complete(_SYSTEM_PROMPT, user)
            raw = json.loads(text)
            concerns = raw.get("concerns") or list(STANDARD_CONCERNS)
            return {
                "concerns": list(concerns),
                "recommend_kill": bool(raw.get("recommend_kill", False)),
            }
        except Exception:
            return {"concerns": list(STANDARD_CONCERNS), "recommend_kill": False}
