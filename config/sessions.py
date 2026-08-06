"""SAST trading-session windows. SEED VALUES ONLY.

These are the spec's §8 sessions, in SAST. They are a starting frame for reporting.
In Phase 1b the REAL session boundaries are DERIVED from the measured cost map
(telemetry/costmap.py), not from this table. Do not encode strategy logic against
these values; they exist only to label hours in early reports.
"""
from __future__ import annotations

# (name, start_hour_sast, end_hour_sast, size_multiplier_hint)
SESSIONS = [
    ("Sydney", 0, 9, 0.375),
    ("Tokyo", 2, 11, 0.5),
    ("Tokyo/London overlap", 10, 11, 0.75),
    ("London", 9, 18, 1.0),
    ("London/NY overlap", 14, 18, 1.0),
    ("New York", 15, 22, 1.0),
]

# Hours to avoid always (SAST): Sunday reopen, late Friday, ~midnight rollover.
# Encoded as advisory notes for reports, not as trading rules.
AVOID_NOTES = [
    "Sunday reopen — widest spreads of the week",
    "Late Friday — thinning liquidity",
    "~00:00 SAST daily rollover — swap charged (triple on Wednesdays)",
]
