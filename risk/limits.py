"""The Risk Officer — Phase 1d interface, stubbed FAIL-CLOSED.

This is plain, deterministic code. It has NO prompt, NO AI, NO override path, by design
(spec §1, §3.6). It is the last thing between the system and the account.

Until the owner-confirmed hard limits (§1) are written in and the full checks are built
and unit-tested in Phase 1d, this stub DENIES every order. Fail-closed is the only safe
default: a risk layer that is not yet configured must never permit a trade.

Phase 1a is passive and never calls this. It exists now so no execution path can be
wired up without going through a (currently denying) risk gate.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class Limits:
    # All None until the owner locks §1 numbers. None == not configured == deny.
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_position_pct: float | None = None
    max_total_exposure_pct: float | None = None
    max_correlated_exposure_pct: float | None = None
    leverage_cap: float | None = None


class RiskOfficer:
    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = limits or Limits()

    def _configured(self) -> bool:
        return all(v is not None for v in vars(self.limits).values())

    def permit(self, *_args, **_kwargs) -> Decision:
        """Deny until §1 limits are configured and Phase 1d checks are built."""
        if not self._configured():
            return Decision(False, "risk limits not configured — fail-closed deny (Phase 1d pending)")
        # Phase 1d: real per-order / per-account checks go here. Still deny until built.
        return Decision(False, "risk checks not yet implemented (Phase 1d)")
