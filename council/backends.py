"""Pluggable model backends for the Council.

IRON RULE: none of these decide anything. They return text or JSON proposals and critiques.
The mock backend is deterministic and anti-hallucination: it never invents citations or
arXiv ids and only proposes strategy kinds the registry actually knows about.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

import numpy as np
from dotenv import load_dotenv

from council.budget import GUARD

# Ensure .env is loaded no matter which entry point imports the backends (a standalone
# `python -m scout.scout` doesn't import config.settings). No-op when there is no .env
# (e.g. CI/Render, where the keys are real environment variables).
load_dotenv()


def _extract_json(text: str) -> str:
    """Pull the first JSON object out of a model reply (handles ``` fences / prose)."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text

try:  # Prefer the real registry; fall back so this module imports even if it is absent.
    from strategy.registry import kinds_at_or_below
except Exception:  # pragma: no cover - defensive import
    _FALLBACK_RUNGS: dict[int, list[str]] = {
        0: ["buy_hold", "random"],
        2: ["ma_trend"],
        3: ["vol_scaled"],
        4: ["multi_timeframe"],
        5: ["mean_reversion"],
    }

    def kinds_at_or_below(rung: int) -> list[str]:
        out: list[str] = []
        for r in sorted(_FALLBACK_RUNGS):
            if r <= rung:
                out.extend(_FALLBACK_RUNGS[r])
        return out


# The generic red-team checklist. Honest, non-fabricated, always worth checking.
STANDARD_CONCERNS = [
    "lookahead: is every signal shifted so bar t uses only data <= t-1?",
    "overfitting: were these params tuned on the same data used to judge them?",
    "regime dependence: does the edge survive a different market regime?",
    "costs: does it still win after spread and commission?",
    "slippage: are fills assumed better than a live $10 account would get?",
]


class ModelBackend(ABC):
    """Abstract text-completion backend. Subclasses may add JSON helpers."""

    name: str = "backend"

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return a raw text completion for the given system + user prompt."""


class MockBackend(ModelBackend):
    """Deterministic offline backend. Same (seed, round) always yields the same proposal."""

    def __init__(self, seed: int = 0, name: str = "mock") -> None:
        self.seed = seed
        self.name = name

    def complete(self, system: str, user: str) -> str:
        """Not really used offline. Returns a short honest placeholder string."""
        return "MOCK-OFFLINE: no model call was made."

    def propose_json(self, context: dict) -> dict:
        """Pick a kind allowed by context["max_rung"] and derive reasonable params.

        Deterministic: a numpy generator is seeded with self.seed + round_index so
        successive rounds differ but every run is reproducible.
        """
        round_index = int(context.get("round_index", 0))
        max_rung = int(context.get("max_rung", 0))
        rng = np.random.default_rng(self.seed + round_index)

        allowed = kinds_at_or_below(max_rung)
        if not allowed:
            allowed = ["buy_hold"]

        # Vary the chosen kind by round while staying within the allowed set.
        kind = allowed[round_index % len(allowed)]
        params = self._params_for(kind, rng)
        rationale = (
            f"Mock proposal for {kind}: a rung-appropriate baseline to feed the backtest. "
            "This is a placeholder rationale from the deterministic offline backend."
        )
        return {"kind": kind, "params": params, "rationale": rationale}

    @staticmethod
    def _params_for(kind: str, rng: np.random.Generator) -> dict:
        """Reasonable in-range params for a kind, drawn from the seeded generator."""
        if kind == "buy_hold":
            return {}
        if kind == "random":
            return {"seed": int(rng.integers(0, 10_000))}
        if kind == "ma_trend":
            fast = int(rng.integers(5, 25))
            slow = fast + int(rng.integers(10, 60))
            return {"fast": fast, "slow": slow}
        if kind == "vol_scaled":
            fast = int(rng.integers(5, 25))
            slow = fast + int(rng.integers(10, 60))
            return {
                "fast": fast,
                "slow": slow,
                "vol_window": int(rng.integers(10, 40)),
                "target_vol": round(float(rng.uniform(0.05, 0.20)), 3),
            }
        if kind == "multi_timeframe":
            base = int(rng.integers(5, 15))
            windows = (base, base * 2, base * 4)
            return {"windows": windows}
        if kind == "mean_reversion":
            return {
                "window": int(rng.integers(10, 40)),
                "z_entry": round(float(rng.uniform(1.5, 2.5)), 2),
                "z_exit": round(float(rng.uniform(0.2, 0.8)), 2),
            }
        return {}

    def critique_json(self, proposal) -> dict:
        """The standard red-team checklist. Honest, generic, non-fabricated."""
        return {"concerns": list(STANDARD_CONCERNS)}


class AnthropicBackend(ModelBackend):
    """Claude backend. Falls back (via RuntimeError) if the key or package is missing."""

    def __init__(self, name: str = "anthropic") -> None:
        self.name = name
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(f"anthropic package unavailable: {exc}") from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        # Current default per Claude API guidance. Override with COUNCIL_ANTHROPIC_MODEL.
        self.model = os.environ.get("COUNCIL_ANTHROPIC_MODEL", "claude-opus-5")

    MAX_TOKENS = 4096

    def complete(self, system: str, user: str) -> str:
        # Refuse before spending, not after. Opus 5 thinks by default and thinking bills as
        # output, so the guard plans against the full max_tokens ceiling.
        GUARD.check(self.model, system, user, self.MAX_TOKENS)
        # Opus 5 thinks by default; give room so the JSON body is not truncated.
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        usage = getattr(msg, "usage", None)
        GUARD.record(self.model,
                     int(getattr(usage, "input_tokens", 0) or 0),
                     int(getattr(usage, "output_tokens", 0) or 0))
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return _extract_json("".join(parts))


class GeminiBackend(ModelBackend):
    """Gemini backend over the REST API (via requests).

    Deliberately avoids the google-generativeai SDK: it pins protobuf >=5, which conflicts
    with ctrader-open-api (protobuf 3.20.1) used by the live data path. REST keeps both alive.
    Tries the API-key query param first, then a Bearer token (covers AQ.* OAuth-style keys).
    """

    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, name: str = "gemini") -> None:
        self.name = name
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.model = os.environ.get("COUNCIL_GEMINI_MODEL", "gemini-2.5-flash")

    def _post(self, headers: dict, params: dict, body: dict):
        import requests
        return requests.post(f"{self.BASE}/{self.model}:generateContent",
                             headers=headers, params=params, json=body, timeout=60)

    MAX_TOKENS = 2048

    def complete(self, system: str, user: str) -> str:
        # Gemini is not in the price table, so the guard prices it at the worst known rate.
        # That over-estimates, which is the safe direction for a cap.
        GUARD.check(self.model, system, user, self.MAX_TOKENS)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": self.MAX_TOKENS, "temperature": 0.6},
        }
        # API-key form first; on auth failure retry as a Bearer token.
        resp = self._post({}, {"key": self.api_key}, body)
        if resp.status_code in (401, 403):
            resp = self._post({"Authorization": f"Bearer {self.api_key}"}, {}, body)
        resp.raise_for_status()
        data = resp.json()
        um = data.get("usageMetadata", {})
        GUARD.record(self.model,
                     int(um.get("promptTokenCount", 0) or 0),
                     int(um.get("candidatesTokenCount", 0) or 0))
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        return _extract_json(text)


def get_backend(prefer: str = "auto") -> ModelBackend:
    """Return a backend. Try the requested real one; on RuntimeError fall back to Mock.

    "auto" tries Anthropic then Gemini then Mock. Any missing key/package cleanly downgrades.
    Prints which backend is active so the offline path is never silent.
    """
    order: list[str]
    if prefer == "auto":
        order = ["anthropic", "gemini"]
    elif prefer in ("mock", "none"):
        order = []
    else:
        order = [prefer]

    for choice in order:
        try:
            if choice == "anthropic":
                backend = AnthropicBackend()
            elif choice == "gemini":
                backend = GeminiBackend()
            else:
                continue
            print(f"[council] active backend: {backend.name}")
            return backend
        except RuntimeError:
            continue

    backend = MockBackend()
    print(f"[council] active backend: {backend.name} (deterministic offline)")
    return backend
