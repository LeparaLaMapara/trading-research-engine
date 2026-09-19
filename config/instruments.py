"""The instrument basket for telemetry. Owner can edit this list.

Chosen to span the cost/liquidity spectrum the spec cares about: the deepest major
(EURUSD), other USD majors, JPY crosses (different digits), the Antipodeans (Asia-Pac
sessions), and gold (XAUUSD). Phase 1a measures the real cost of each, by hour.
"""
from __future__ import annotations

# Symbol names as cTrader reports them (symbolName, upper-cased on match).
BASKET = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "NZDUSD",
    "AUDJPY",
    "NZDJPY",
    "XAUUSD",
]


# --- The research universe -------------------------------------------------------------
#
# BASKET above is the TELEMETRY basket: instruments whose real spread is measured tick by
# tick. This is the wider RESEARCH universe, spanning asset classes rather than FX alone.
#
# Why breadth matters more than depth here. A small account's only structural advantage is
# access to opportunities too small for a large fund to bother with, and that advantage is
# useless if the search only ever looks at three FX pairs. Cross-asset structure (a metal
# against its currency, an index against its constituents' currency, crypto against the
# dollar) is also where most of the opportunity classes in docs/ARCHITECTURE.md live.
#
# Verified present and enabled on the live account (46748922) on 2026-09-15. The demo
# account carries 830 symbols against live's 348, so this list is taken from LIVE: a
# strategy researched on an instrument the live account cannot trade is wasted work.
RESEARCH_UNIVERSE: dict[str, list[str]] = {
    "fx_major":   ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"],
    "fx_cross":   ["EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD"],
    "metal":      ["XAUUSD", "XAGUSD", "XAUEUR"],
    "index":      ["US500", "DE40", "HK50", "AUS200"],
    "energy":     ["XTIUSD", "XBRUSD"],
    "crypto":     ["BTCUSD", "ETHUSD", "ADAUSD"],
}


def universe(*classes: str) -> list[str]:
    """Flat symbol list for the named asset classes, or all of them when none are given."""
    keys = classes or tuple(RESEARCH_UNIVERSE)
    return [s for k in keys for s in RESEARCH_UNIVERSE.get(k, [])]


# Measure what we research. With the telemetry basket at 8 and the universe at 24, sixteen
# instruments were backtested on a DEFAULT spread, and at small size cost is the dominant
# term, so those results were guesses. Extended 2026-09-16, original eight first.
BASKET = BASKET + [s for s in universe() if s not in BASKET]


#: The EXTENDED universe, 2026-09-19. Breadth is the one lever the evidence supports (Carver:
#: Sharpe 0.35 on one instrument, 0.61 on eight near-independent ones), and pooled models need
#: more instruments to have enough samples. Research only: the daily CI run keeps the core 24.
#: Every symbol verified present on the live account (data/live_symbols.json, 348 symbols).
#: Dated futures (WTI_*, UST10Y_*, VIX_*) are excluded until a continuous series is built.
EXTENDED_UNIVERSE: dict[str, list[str]] = {
    "fx_major":   ["USDZAR", "USDMXN", "USDNOK", "USDSEK", "USDSGD", "USDPLN"],
    "fx_cross":   ["AUDNZD", "EURCHF", "AUDCAD", "CADJPY", "CHFJPY", "GBPAUD", "GBPCAD",
                   "EURCAD", "NZDJPY", "EURNOK", "EURSEK", "EURZAR", "GBPCHF", "EURNZD"],
    "metal":      ["XPTUSD", "XPDUSD"],
    "index":      ["US30", "USTEC", "US2000", "JP225", "UK100", "F40", "STOXX50", "SMI",
                   "CHINA50", "SA40", "ES35", "IT40", "CA60"],
    "energy":     ["XNGUSD"],
    "crypto":     ["SOLUSD", "XRPUSD", "LTCUSD", "BCHUSD", "DOTUSD"],
}


def extended_universe(*classes: str) -> list[str]:
    """Core universe plus the extended research-only symbols."""
    keys = classes or tuple(RESEARCH_UNIVERSE)
    core = universe(*classes)
    return core + [s for k in keys for s in EXTENDED_UNIVERSE.get(k, []) if s not in core]


def asset_class_of(symbol: str) -> str | None:
    """Which class a symbol belongs to. Cross-asset research needs to know."""
    up = symbol.upper()
    for table in (RESEARCH_UNIVERSE, EXTENDED_UNIVERSE):
        for k, syms in table.items():
            if up in syms:
                return k
    return None
