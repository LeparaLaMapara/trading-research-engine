"""The Scout: hunt real research and turn it into testable strategy ideas (spec §3.1).

Pipeline per paper:
  fetch (arXiv, real id + real abstract)  ->  ground a Transfer Card in the fetched text
  ->  map the method to an implementable strategy kind + params  ->  hand to the harness.

Anti-hallucination (spec §5) is structural: `identifier` is always the arXiv id returned by
the fetch (never the model's memory), the fetched `abstract` is stored on the card, and the
LLM is only ever shown text that was actually fetched. With no live model, mapping falls back
to a transparent keyword heuristic. With no network, it returns honest MOCK-OFFLINE cards
(never a fabricated citation).

Run:  python -m scout.scout                        # preview live discoveries
      python -m scout.scout --keywords "mean reversion" -n 5
"""
from __future__ import annotations

import argparse
import json
import uuid

from council.backends import MockBackend, get_backend
from research.schemas import TransferCard
from scout import sources

# Strategies the harness can actually run (a paper maps to one of these, or to nothing yet).
ALLOWED_KINDS = ["buy_hold", "ma_trend", "vol_scaled", "multi_timeframe", "mean_reversion"]

_HEURISTICS = [
    ("mean_reversion", ("mean revers", "mean-revers", "reversal", "contrarian", "overreact")),
    ("ma_trend", ("momentum", "trend follow", "trend-follow", "time series momentum",
                  "moving average")),
    ("vol_scaled", ("volatility target", "vol target", "risk parity", "volatility scal",
                    "vol scal")),
    ("multi_timeframe", ("multi-scale", "multiple horizon", "multi-horizon", "multi timeframe")),
]

_SYSTEM = (
    "You read a finance research paper's abstract and map its core method to ONE implementable "
    "trading strategy. Use only what the abstract states; do not invent results or citations. "
    "Allowed kinds: buy_hold, ma_trend, vol_scaled, multi_timeframe, mean_reversion, or null if "
    "the method genuinely needs a new implementation. Respond with STRICT JSON: "
    '{"market_claim": str, "assumptions_required": [str], "failure_regime": str, '
    '"kind": str|null, "params": object}. No prose outside the JSON.'
)


def _heuristic_kind(text: str) -> str | None:
    low = text.lower()
    for kind, needles in _HEURISTICS:
        if any(n in low for n in needles):
            return kind
    return None


class Scout:
    """Fetches real papers and grounds Transfer Cards in them. Never fabricates a citation."""

    def __init__(self, backend=None) -> None:
        self.backend = backend

    # -- the real path ----------------------------------------------------
    def discover(self, n: int = 5, keywords: str | None = None) -> list[TransferCard]:
        papers = sources.fetch_arxiv(keywords=keywords, max_results=n)
        if not papers:
            return self.transfer_cards(min(n, 2))  # offline / no network -> honest placeholders
        return [self._card_from_paper(p) for p in papers]

    def _card_from_paper(self, paper: dict) -> TransferCard:
        card = TransferCard(
            id=str(uuid.uuid4()),
            title=paper["title"],
            identifier=paper["identifier"],   # REAL arXiv id, from the fetch
            discipline="q-fin/stat.ML",
            market_claim="",
            url=paper.get("url", ""),
            abstract=paper["abstract"],
        )
        synth = self._synthesize(paper)
        card.market_claim = synth.get("market_claim") or paper["abstract"][:240]
        card.assumptions_required = synth.get("assumptions_required") or []
        card.failure_regime = synth.get("failure_regime") or ""
        kind = synth.get("kind")
        card.mapped_kind = kind if kind in ALLOWED_KINDS else None
        card.mapped_params = synth.get("params") or {}
        return card

    def _synthesize(self, paper: dict) -> dict:
        """LLM synthesis grounded in the fetched abstract; heuristic fallback offline."""
        if self.backend is None or isinstance(self.backend, MockBackend):
            return {"kind": _heuristic_kind(paper["title"] + " " + paper["abstract"]),
                    "market_claim": paper["abstract"][:240], "params": {}}
        try:
            text = self.backend.complete(
                _SYSTEM, f"Title: {paper['title']}\nAbstract: {paper['abstract']}\nMap it.")
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("not an object")
            return raw
        except Exception:  # noqa: BLE001 - never fabricate; degrade to heuristic
            return {"kind": _heuristic_kind(paper["title"] + " " + paper["abstract"]),
                    "market_claim": paper["abstract"][:240], "params": {}}

    # -- offline honest placeholders (no fabricated identifiers) -----------
    def transfer_cards(self, n: int = 2) -> list[TransferCard]:
        """Honest offline placeholders. identifier == MOCK-OFFLINE, never a fake arXiv id/DOI."""
        effects = [
            ("prices show short-horizon mean reversion intraday", "mean_reversion",
             "market microstructure"),
            ("returns trend: medium-horizon moves tend to persist", "ma_trend", "asset pricing"),
            ("volatility clusters, so scaling size by recent vol steadies risk", "vol_scaled",
             "statistics / econophysics"),
        ]
        cards: list[TransferCard] = []
        for claim, kind, disc in effects[:max(1, n)]:
            cards.append(TransferCard(
                id=str(uuid.uuid4()),
                title=f"[offline placeholder] {claim}",
                identifier="MOCK-OFFLINE",
                discipline=disc,
                market_claim=claim + " (OFFLINE PLACEHOLDER: no paper fetched; not a citation)",
                mapped_kind=kind,
            ))
        return cards


def main() -> None:
    p = argparse.ArgumentParser(description="Preview the Scout's live paper discoveries.")
    p.add_argument("-n", type=int, default=5)
    p.add_argument("--keywords", default=None)
    args = p.parse_args()
    scout = Scout(backend=get_backend())
    for c in scout.discover(args.n, args.keywords):
        print(f"\n{c.identifier}  -> maps to: {c.mapped_kind}")
        print(f"  {c.title}")
        print(f"  claim: {c.market_claim[:160]}")


if __name__ == "__main__":
    main()
