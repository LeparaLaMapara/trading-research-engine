"""The learning loop must be able to forget, and its win rate must be able to say no.

A memory store that only grows makes an agent worse, because a longer context degrades the
model it is meant to help. So the properties worth locking are not "does it remember" but
"does it measure whether remembering helped, and does it drop what did not".
"""
from __future__ import annotations

import pytest

from research.lessons import LessonStore, _fingerprint, lessons_from_cycle


@pytest.fixture()
def store(tmp_path):
    return LessonStore(str(tmp_path / "research.db"))


def test_the_same_insight_is_amended_not_duplicated(store):
    """Delta updates. Rewriting or duplicating is what causes the store to drift generic."""
    store.add("Mean reversion loses money on EURUSD.", "evidence A")
    store.add("mean reversion loses money on eurusd", "evidence B")
    rows = store.all()
    assert len(rows) == 1
    assert "evidence A" in rows[0]["evidence"] and "evidence B" in rows[0]["evidence"]


def test_fingerprint_ignores_case_and_punctuation():
    assert _fingerprint("Costs matter!") == _fingerprint("costs  matter")
    assert _fingerprint("Costs matter") != _fingerprint("Costs do not matter")


def test_a_lesson_that_never_helps_is_retired(store):
    store.add("A useless lesson.")
    fps = [ln["fingerprint"] for ln in store.active()]
    for _ in range(12):
        store.mark_shown(fps)          # shown repeatedly, never credited
    assert store.evict() == fps
    assert store.active() == []        # no longer injected into context


def test_a_lesson_that_helps_survives(store):
    store.add("A useful lesson.")
    fps = [ln["fingerprint"] for ln in store.active()]
    for _ in range(12):
        store.mark_shown(fps)
        store.mark_helped(fps)
    assert store.evict() == []
    assert len(store.active()) == 1


def test_the_playbook_is_bounded(store):
    """Unbounded memory is the failure mode: more context makes the model worse, not better."""
    for i in range(40):
        store.add(f"Lesson number {i} about something.")
    assert len(store.active()) <= 8


def test_untested_lessons_get_a_hearing_before_proven_ones(store):
    """A new insight must reach the context at least once, or it can never earn its place."""
    store.add("An old lesson.")
    old = [ln["fingerprint"] for ln in store.active()]
    for _ in range(5):
        store.mark_shown(old)
        store.mark_helped(old)
    store.add("A brand new lesson.")
    assert "A brand new lesson." in [ln["lesson"] for ln in store.active()]


def test_retired_lessons_stay_recorded(store):
    """Retired, not deleted: that it was tried and found useless is itself worth knowing,
    otherwise the same dead idea gets re-learned forever."""
    store.add("Doomed.")
    fps = [ln["fingerprint"] for ln in store.active()]
    for _ in range(12):
        store.mark_shown(fps)
    store.evict()
    assert len(store.all(include_retired=True)) == 1
    assert store.all(include_retired=True)[0]["retired"] == 1


# ------------------------------------------------------- deterministic distillation


class _P:
    def __init__(self, kind):
        self.kind = kind


def _trial(kind, dsr, dev=-1.0, hold=-1.0, verdict="FAIL"):
    return {"proposal": _P(kind), "dsr": dsr, "verdict": verdict,
            "wf": {"dev_summary": {"sharpe": dev}, "holdout_summary": {"sharpe": hold}}}


def test_lessons_are_derived_from_results_not_invented():
    out = lessons_from_cycle([_trial("ma_trend", 0.001)], "EURUSD", honest_n=24)
    assert out, "a cycle where everything failed should teach something"
    for text, evidence in out:
        assert any(ch.isdigit() for ch in evidence), "every lesson cites a number"


def test_overfitting_caught_in_the_act_is_recorded():
    """Good in-sample, dead out-of-sample is the single most valuable thing to remember."""
    out = lessons_from_cycle([_trial("vol_scaled", 0.2, dev=1.4, hold=-0.3)], "XAUUSD", 30)
    assert any("never seen" in t for t, _ in out)


def test_no_lessons_when_nothing_was_tested():
    assert lessons_from_cycle([{"proposal": _P("x"), "verdict": "SKIPPED"}], "EURUSD", 1) == []
