"""Hard spend cap for the council.

Why this exists. Between 2026-08-07 and 2026-09-15 the daily GitHub Actions run proposed six
strategies per symbol on three symbols, every day, and threw every one of them away at the
next step because the failure registry had blacklisted the whole search space. The workflow
exited 0 throughout, so nothing surfaced. Roughly forty days of Claude and Gemini calls bought
nothing.

The rule this enforces: check the projected cost BEFORE the call, not after. A guard that only
reports spend is an invoice, not a guard.

Scope: this is a per-process cap, which is what a single scheduled research run needs. It is
not a substitute for a gateway-level cap (a LiteLLM virtual key with `max_budget`, or an
OpenRouter provisioning key with `limit`), which rejects an over-budget request before it
reaches the provider and therefore survives a bug in this file. Phase 3 of the plan moves the
hard ceiling there and leaves this as the in-run early stop.
"""
from __future__ import annotations

import os


class BudgetExceeded(RuntimeError):
    """Raised before a call that would push the run over its cap."""


# USD per 1M tokens, (input, output). Anthropic first-party rates.
# Sources: Claude API pricing as of 2026-09-25.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # Google standard tier, checked 2026-09-29 at ai.google.dev/gemini-api/docs/pricing.
    # Output includes thinking tokens.
    "gemini-2.5-flash": (0.30, 2.50),
}

# Other models are absent unless their price was checked at the source. An unknown model is priced at the most
# expensive rate in the table, so the guard can only ever over-estimate. Under-estimating is
# the failure mode that costs money; over-estimating just stops the run early and says so.
_WORST = max(PRICES.values(), key=lambda p: p[1])


def price_of(model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens. Unknown models price at the worst known rate."""
    return PRICES.get(model, _WORST)


def estimate_tokens(text: str) -> int:
    """Rough token count for a pre-call check. Deliberately crude and biased high.

    Real accounting uses the provider's reported usage after the call. This only has to be
    good enough to refuse a call that would blow the cap, so ~3.5 chars per token errs toward
    over-counting rather than under.
    """
    return int(len(text) / 3.5) + 1


class BudgetGuard:
    """Per-run spend and call cap. Construct once and share across backends."""

    def __init__(self, max_usd: float | None = None, max_calls: int | None = None) -> None:
        self.max_usd = float(os.environ.get("COUNCIL_MAX_USD_PER_RUN", "1.00")
                             if max_usd is None else max_usd)
        self.max_calls = int(os.environ.get("COUNCIL_MAX_CALLS_PER_RUN", "60")
                             if max_calls is None else max_calls)
        self.spent_usd = 0.0
        self.calls = 0
        self.by_model: dict[str, dict[str, float]] = {}

    def cost(self, model: str, in_tokens: int, out_tokens: int) -> float:
        p_in, p_out = price_of(model)
        return (in_tokens * p_in + out_tokens * p_out) / 1_000_000

    def check(self, model: str, system: str, user: str, max_out_tokens: int) -> None:
        """Refuse the call if it could take the run over budget. Worst case is assumed:
        the full `max_out_tokens` are generated. On Opus 5 thinking is on by default and
        thinking tokens bill as output, so the ceiling is the honest number to plan against."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"call cap reached: {self.calls}/{self.max_calls} calls this run"
            )
        projected = self.cost(model, estimate_tokens(system) + estimate_tokens(user),
                              max_out_tokens)
        if self.spent_usd + projected > self.max_usd:
            raise BudgetExceeded(
                f"budget cap: spent ${self.spent_usd:.4f}, this call could cost up to "
                f"${projected:.4f}, cap is ${self.max_usd:.2f}. Raise "
                f"COUNCIL_MAX_USD_PER_RUN to continue."
            )

    def record(self, model: str, in_tokens: int, out_tokens: int) -> float:
        """Book actual usage reported by the provider. Returns the cost of this call."""
        c = self.cost(model, in_tokens, out_tokens)
        self.spent_usd += c
        self.calls += 1
        slot = self.by_model.setdefault(model, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
        slot["calls"] += 1
        slot["in"] += in_tokens
        slot["out"] += out_tokens
        slot["usd"] += c
        return c

    def summary(self) -> str:
        parts = [f"{m}: {int(v['calls'])} calls, {int(v['in'])} in, {int(v['out'])} out, "
                 f"${v['usd']:.4f}" for m, v in sorted(self.by_model.items())]
        return (f"[budget] ${self.spent_usd:.4f} of ${self.max_usd:.2f} over {self.calls} calls"
                + ("\n          " + "\n          ".join(parts) if parts else ""))


# Shared by every backend in a run. Tests construct their own.
GUARD = BudgetGuard()
