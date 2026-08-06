"""The Proposer agent: turns context into a StrategyProposal + a FalsifiablePrediction.

It PROPOSES only. It never scores or decides. It avoids re-proposing a kind that already
died for this symbol (from the Failure Registry), and it commits falsifiable bounds so the
agent can be scored later.
"""
from __future__ import annotations

import json
import uuid

from council.backends import MockBackend
from research.schemas import FalsifiablePrediction, StrategyProposal

try:
    from strategy.registry import kinds_at_or_below, rung_of
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

    def rung_of(kind: str) -> int:
        for r, kinds in _FALLBACK_RUNGS.items():
            if kind in kinds:
                return r
        return 0


_SYSTEM_PROMPT = (
    "You propose quantitative trading strategy specs for a research engine. "
    "You NEVER decide whether to trade; a deterministic backtest judges every proposal. "
    "Rules: only propose from the allowed kinds; keep params in sensible ranges; state a "
    "plain-English economic rationale; never fabricate numbers. "
    "Allowed kinds by rung: 0 buy_hold/random, 2 ma_trend, 3 vol_scaled, 4 multi_timeframe, "
    "5 mean_reversion. Respond with STRICT JSON: "
    '{"kind": str, "params": object, "rationale": str}. No prose outside the JSON.'
)


class Proposer:
    """Proposes a strategy spec for a given context and round."""

    def __init__(self, backend) -> None:
        self.backend = backend

    def _rung_of(self, kind: str, max_rung: int) -> int:
        try:
            return rung_of(kind)
        except Exception:
            return max_rung

    def _mock_proposal(self, context: dict, round_index: int) -> dict:
        mock = self.backend if isinstance(self.backend, MockBackend) else MockBackend()
        ctx = dict(context)
        ctx["round_index"] = round_index
        return mock.propose_json(ctx)

    def _avoid_seen(self, kind: str, context: dict, round_index: int) -> str:
        """If `kind` already died for this symbol, pick another allowed, unseen kind."""
        max_rung = int(context.get("max_rung", 0))
        seen = context.get("seen_failures") or []
        seen_kinds = {f.get("strategy_kind") for f in seen}
        if kind not in seen_kinds:
            return kind
        allowed = kinds_at_or_below(max_rung)
        for i in range(len(allowed)):
            candidate = allowed[(round_index + i) % len(allowed)]
            if candidate not in seen_kinds:
                return candidate
        return kind  # every allowed kind has died; keep the original (backtest still judges)

    def propose(
        self, context: dict, round_index: int, committed_at: str = ""
    ) -> StrategyProposal:
        """Build a StrategyProposal and attach a FalsifiablePrediction.

        For MockBackend, uses its deterministic propose_json. For real backends, prompts for
        STRICT JSON and parses it; on any parse failure it falls back to a mock proposal.
        """
        max_rung = int(context.get("max_rung", 0))
        symbol = context.get("symbol", "UNKNOWN")
        period = context.get("period", "UNKNOWN")

        if isinstance(self.backend, MockBackend):
            raw = self._mock_proposal(context, round_index)
        else:
            user = (
                f"symbol={symbol} period={period} max_rung={max_rung} "
                f"round={round_index}. Prior failures for this symbol: "
                f"{[f.get('strategy_kind') for f in (context.get('seen_failures') or [])]}. "
                "Propose one strategy."
            )
            try:
                text = self.backend.complete(_SYSTEM_PROMPT, user)
                raw = json.loads(text)
                if not isinstance(raw, dict) or "kind" not in raw:
                    raise ValueError("missing kind")
            except Exception:
                raw = self._mock_proposal(context, round_index)

        kind = raw.get("kind", "buy_hold")
        params = raw.get("params", {}) or {}
        rationale = raw.get("rationale", "")

        # Never re-propose a kind that already died for this symbol.
        substituted = self._avoid_seen(kind, context, round_index)
        if substituted != kind:
            import numpy as np

            mock = self.backend if isinstance(self.backend, MockBackend) else MockBackend()
            params = mock._params_for(substituted, np.random.default_rng(round_index))
            rationale = (
                f"Substituted to {substituted}: prior {kind} failures for {symbol} avoided. "
                + rationale
            )
            kind = substituted

        rung = self._rung_of(kind, max_rung)

        proposal = StrategyProposal(
            id=str(uuid.uuid4()),
            kind=kind,
            params=params,
            rung=rung,
            symbol=symbol,
            period=period,
            agent=getattr(self.backend, "name", "backend"),
            rationale=rationale,
        )
        proposal.prediction = self._prediction_for(proposal, committed_at)
        return proposal

    def _prediction_for(
        self, proposal: StrategyProposal, committed_at: str
    ) -> FalsifiablePrediction:
        """Sensible falsifiable bounds by kind. These are commitments, not judgements."""
        kind = proposal.kind
        # Conservative defaults; tighter/looser by kind complexity.
        bounds = {
            "buy_hold": (0.0, 0.40, 0.45, 0.60, 0.0, 1.0, 0.5),
            "random": (-0.5, 0.60, 0.40, 0.60, 5.0, 60.0, 0.3),
            "ma_trend": (0.3, 0.30, 0.35, 0.55, 1.0, 12.0, 0.5),
            "vol_scaled": (0.5, 0.25, 0.35, 0.55, 1.0, 12.0, 0.55),
            "multi_timeframe": (0.4, 0.30, 0.35, 0.55, 1.0, 15.0, 0.5),
            "mean_reversion": (0.5, 0.20, 0.45, 0.65, 3.0, 40.0, 0.55),
        }
        sg, dd, wlo, whi, tlo, thi, conf = bounds.get(
            kind, (0.0, 0.40, 0.40, 0.60, 0.0, 30.0, 0.4)
        )
        return FalsifiablePrediction(
            prediction_id=str(uuid.uuid4()),
            strategy_id=proposal.id,
            agent=proposal.agent,
            committed_at=committed_at,
            sharpe_gt=sg,
            max_dd_lt=dd,
            win_rate_lo=wlo,
            win_rate_hi=whi,
            trades_per_month_lo=tlo,
            trades_per_month_hi=thi,
            confidence=conf,
        )
