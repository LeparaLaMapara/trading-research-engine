"""Proposal validator: reject strategies that encode prohibited risk patterns.

Martingale-family behaviour (averaging into losses, grids, doubling on a loss, loss
pyramiding) turns a small edge into a fat left tail and is banned by the project spec. This
is deterministic code, not an LLM judgement: it screens proposals before they reach the
backtest so no such shape ever gets tested or funded.
"""
from __future__ import annotations

# Substrings that mark a martingale-family pattern anywhere in the kind or params.
_PROHIBITED_SUBSTRINGS = (
    "martingale",
    "grid",
    "average_down",
    "averaging",
    "double_down",
    "pyramid_loss",
)

_MAX_LEVERAGE_CAP = 5.0


def _contains_prohibited(text: str) -> str | None:
    lowered = text.lower()
    for token in _PROHIBITED_SUBSTRINGS:
        if token in lowered:
            return token
    return None


def validate_proposal(spec: dict) -> tuple[bool, list[str]]:
    """Return (ok, reasons). ok=False if the proposal encodes a prohibited pattern."""
    reasons: list[str] = []
    kind = str(spec.get("kind", ""))
    params = spec.get("params") or {}

    hit = _contains_prohibited(kind)
    if hit is not None:
        reasons.append(f"kind encodes prohibited pattern: '{hit}'")

    for key, value in params.items():
        hit = _contains_prohibited(str(key))
        if hit is not None:
            reasons.append(f"param key encodes prohibited pattern: '{hit}'")
        hit = _contains_prohibited(str(value))
        if hit is not None:
            reasons.append(f"param value encodes prohibited pattern: '{hit}'")

    if params.get("increase_size_on_loss"):
        reasons.append("increase_size_on_loss is a martingale flag and is prohibited")

    try:
        max_lev = float(params.get("max_leverage", 0))
    except (TypeError, ValueError):
        max_lev = 0.0
    if max_lev > _MAX_LEVERAGE_CAP:
        reasons.append(f"max_leverage {max_lev} exceeds cap {_MAX_LEVERAGE_CAP}")

    return (len(reasons) == 0, reasons)
