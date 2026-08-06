"""The Scout agent (spec §3.1): imports cross-discipline ideas as TransferCards.

ANTI-HALLUCINATION IS CRITICAL. Offline, the Scout never invents a resolvable-looking
citation. Its cards carry identifier == "MOCK-OFFLINE" and describe only generic, well-known
market effects, with an explicit note that they are placeholders, not fetched literature.
A real web-enabled backend could fetch real papers later (see TODO), but we never fake one.
"""
from __future__ import annotations

import uuid

from council.backends import MockBackend
from research.schemas import TransferCard

_OFFLINE_NOTE = (
    "OFFLINE PLACEHOLDER: not fetched from literature. identifier is MOCK-OFFLINE, not a "
    "real arXiv id or DOI. Do not cite this as a source."
)

# Generic, well-known effects. No fabricated citations attached.
_OFFLINE_TEMPLATES = [
    {
        "title": "Short-horizon intraday mean reversion",
        "discipline": "market microstructure",
        "market_claim": "prices exhibit short-horizon mean reversion intraday",
        "assumptions_required": [
            "liquid, continuously traded instrument",
            "transaction costs below the reversion edge",
        ],
        "data_required": "intraday bars (1m to 15m) with spread estimates",
        "failure_regime": "trending or news-driven sessions where reversion breaks down",
    },
    {
        "title": "Volatility clustering",
        "discipline": "statistics / econophysics",
        "market_claim": "volatility clusters: large moves tend to follow large moves",
        "assumptions_required": [
            "a usable volatility estimator (e.g. rolling stdev)",
            "position sizing that can scale to target volatility",
        ],
        "data_required": "returns series long enough to estimate rolling volatility",
        "failure_regime": "abrupt regime shifts where past volatility misprices the future",
    },
    {
        "title": "Cross-sectional momentum",
        "discipline": "asset pricing",
        "market_claim": "recent relative winners tend to keep outperforming over weeks",
        "assumptions_required": [
            "a cross-section of comparable instruments",
            "rebalancing costs below the momentum spread",
        ],
        "data_required": "aligned daily returns across several instruments",
        "failure_regime": "sharp momentum crashes at reversals",
    },
]


class Scout:
    """Produces TransferCards. Offline cards are honest placeholders, never fabrications."""

    def __init__(self, backend=None) -> None:
        self.backend = backend

    def _is_offline(self) -> bool:
        return self.backend is None or isinstance(self.backend, MockBackend)

    def transfer_cards(self, n: int = 2) -> list[TransferCard]:
        """Return `n` transfer cards.

        Offline: honest placeholders with identifier == "MOCK-OFFLINE". A real web-enabled
        backend path would fetch actual papers here.
        """
        if self._is_offline():
            cards: list[TransferCard] = []
            for i in range(n):
                t = _OFFLINE_TEMPLATES[i % len(_OFFLINE_TEMPLATES)]
                cards.append(
                    TransferCard(
                        id=str(uuid.uuid4()),
                        title=t["title"],
                        identifier="MOCK-OFFLINE",
                        discipline=t["discipline"],
                        market_claim=t["market_claim"] + f" [{_OFFLINE_NOTE}]",
                        assumptions_required=list(t["assumptions_required"]),
                        data_required=t["data_required"],
                        failure_regime=t["failure_regime"],
                    )
                )
            return cards

        # TODO: real web-enabled backend path. Only emit a TransferCard with a resolvable
        # identifier once the paper has actually been fetched and its text stored. Until then
        # we must never synthesise an arXiv id or DOI. Fall back to offline placeholders.
        self_offline = Scout(backend=None)
        return self_offline.transfer_cards(n)
