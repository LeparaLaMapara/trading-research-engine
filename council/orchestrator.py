"""The Council orchestrator: runs one propose-and-critique round.

The Council PROPOSES and CRITIQUES. It NEVER returns a verdict on whether to trade; there is
no accept/reject field in its output. Judging is done downstream by the backtest harness.
"""
from __future__ import annotations

from council.backends import get_backend
from council.proposer import Proposer
from council.redteam import RedTeam


class Council:
    """Wires a Proposer and a Red Team over (possibly shared) model backends."""

    def __init__(self, proposer_backend=None, redteam_backend=None) -> None:
        self.proposer_backend = proposer_backend or get_backend()
        self.redteam_backend = redteam_backend or self.proposer_backend
        self.proposer = Proposer(self.proposer_backend)
        self.redteam = RedTeam(self.redteam_backend)

    def run_round(self, context: dict, round_index: int, committed_at: str) -> dict:
        """Produce a proposal, its falsifiable prediction, and a critique. No trade verdict."""
        proposal = self.proposer.propose(context, round_index, committed_at=committed_at)
        prediction = getattr(proposal, "prediction", None)
        critique = self.redteam.critique(proposal)
        return {
            "proposal": proposal,
            "prediction": prediction,
            "critique": critique,
        }
