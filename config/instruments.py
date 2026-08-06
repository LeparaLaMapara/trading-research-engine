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
