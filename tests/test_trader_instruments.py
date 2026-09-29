"""The multi-instrument trader: the rollover blackout and per-instrument state keys."""
from __future__ import annotations

import calendar

from scripts import trader_step as T


def _at(hour: int) -> float:
    return calendar.timegm((2026, 9, 29, hour, 30, 0))


def test_blackout_covers_the_rollover_hours_only():
    w = (20, 23)
    assert not T.in_blackout(_at(19), w)
    assert T.in_blackout(_at(20), w)
    assert T.in_blackout(_at(22), w)
    assert not T.in_blackout(_at(23), w)
    assert not T.in_blackout(_at(21), None)


def test_eth_keeps_its_original_state_keys_and_others_are_namespaced(monkeypatch):
    monkeypatch.setattr(T, "SYMBOL", "ETHUSD")
    assert T.sk("decided_bar") == "decided_bar"
    monkeypatch.setattr(T, "SYMBOL", "USDSGD")
    assert T.sk("decided_bar") == "USDSGD:decided_bar"


def test_usdsgd_is_live_with_a_blackout_and_spread_recording():
    rows = {s: (label, blackout, rec) for s, label, blackout, rec in T.INSTRUMENTS}
    assert rows["ETHUSD"] == ("engine-E05", None, False)
    assert rows["USDSGD"] == ("engine-E08", "20-23", True)
