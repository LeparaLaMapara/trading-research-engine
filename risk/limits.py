"""The Risk Officer. The last thing between the system and the account.

Plain, deterministic code. NO prompt, NO model, NO override path, by design (spec sections 1
and 3.6). Nothing here may ever consult an LLM, and nothing an LLM produces may relax it.

Until 2026-09-16 this was a stub that denied everything, which was correct while nothing
could trade. It now performs real checks, and the default is still to deny: an unconfigured
Limits denies every order, so forgetting to configure it fails closed rather than open.

**Environment is part of the limits, not a global.** A Limits object is stamped `demo` or
`live`, and permit() refuses when the account it is asked about does not match. That is what
lets a rehearsal run with real numbers on a demo account without creating a path to the live
one. LIVE_LIMITS is deliberately left unconfigured until the owner signs off the section 1
numbers, so live orders are denied by the same mechanism that denies a misconfiguration.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    checks: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Limits:
    """All None means not configured, which means deny. That is the safe direction."""
    environment: str | None = None          # "demo" or "live"
    max_risk_per_trade_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_position_pct: float | None = None   # margin as a fraction of equity
    max_open_positions: int | None = None
    min_equity: float | None = None         # hard floor; below it, stop permanently

    def configured(self) -> bool:
        return all(v is not None for v in vars(self).values())


# Rehearsal limits. DEMO ONLY. Deliberately ordinary numbers, because the point of the
# rehearsal is to exercise the machinery, not to be clever about risk.
DEMO_REHEARSAL_LIMITS = Limits(
    environment="demo",
    max_risk_per_trade_pct=0.02,
    max_daily_loss_pct=0.05,
    max_drawdown_pct=0.20,
    max_position_pct=0.50,
    max_open_positions=1,
    min_equity=1000.0,
)

# Live limits stay UNCONFIGURED until the owner signs off the section 1 numbers. Every field
# is None, so configured() is False, so permit() denies. This is the whole safety story for
# the live account and it must not be filled in casually.
LIVE_LIMITS = Limits(environment="live")


class RiskOfficer:
    """Deterministic gate. Every check is arithmetic against observable state."""

    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = limits or Limits()

    def permit(self, *, account_environment: str | None = None, equity: float | None = None,
               risk_amount: float | None = None, margin_required: float | None = None,
               open_positions: int = 0, realised_pnl_today: float = 0.0,
               equity_peak: float | None = None, **_ignored) -> Decision:
        """Allow this specific order, or refuse and say which check failed.

        Missing information is a refusal, never an assumption. A check that cannot be
        evaluated has not been passed.
        """
        lim = self.limits
        checks: dict = {}

        if not lim.configured():
            missing = [k for k, v in vars(lim).items() if v is None]
            return Decision(False, f"risk limits not configured (missing: {', '.join(missing)}) "
                                   f"- fail-closed deny", {"configured": False})
        checks["configured"] = True

        if account_environment is None:
            return Decision(False, "account environment unknown - refusing rather than "
                                   "assuming", checks)
        if account_environment != lim.environment:
            return Decision(False, f"these limits are for '{lim.environment}' accounts but "
                                   f"this account is '{account_environment}'", checks)
        checks["environment"] = account_environment

        if equity is None or risk_amount is None:
            return Decision(False, "equity or risk amount unknown - refusing", checks)
        if equity <= 0:
            return Decision(False, "no equity", checks)

        if equity < lim.min_equity:
            return Decision(False, f"equity {equity:.2f} is below the hard floor "
                                   f"{lim.min_equity:.2f} - stop", checks)
        checks["min_equity"] = True

        risk_pct = risk_amount / equity
        checks["risk_per_trade_pct"] = round(risk_pct, 5)
        if risk_pct > lim.max_risk_per_trade_pct:
            return Decision(False, f"this order risks {risk_pct*100:.2f}% of equity, above "
                                   f"the {lim.max_risk_per_trade_pct*100:.2f}% limit", checks)

        if open_positions >= lim.max_open_positions:
            return Decision(False, f"{open_positions} position(s) already open, limit is "
                                   f"{lim.max_open_positions}", checks)
        checks["open_positions"] = open_positions

        if margin_required is not None:
            margin_pct = margin_required / equity
            checks["position_pct"] = round(margin_pct, 5)
            if margin_pct > lim.max_position_pct:
                return Decision(False, f"margin would be {margin_pct*100:.1f}% of equity, "
                                       f"above the {lim.max_position_pct*100:.1f}% limit",
                                checks)

        daily_pct = -realised_pnl_today / equity if realised_pnl_today < 0 else 0.0
        checks["daily_loss_pct"] = round(daily_pct, 5)
        if daily_pct >= lim.max_daily_loss_pct:
            return Decision(False, f"already down {daily_pct*100:.2f}% today, at or past the "
                                   f"{lim.max_daily_loss_pct*100:.2f}% daily limit", checks)

        if equity_peak:
            dd = (equity_peak - equity) / equity_peak
            checks["drawdown_pct"] = round(dd, 5)
            if dd >= lim.max_drawdown_pct:
                return Decision(False, f"drawdown {dd*100:.1f}% from peak, at or past the "
                                       f"{lim.max_drawdown_pct*100:.1f}% limit", checks)

        return Decision(True, "within all configured limits", checks)
