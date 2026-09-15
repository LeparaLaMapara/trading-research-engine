"""The audit is what watches the rest of the system, so its own failure modes matter most.

The property under test everywhere here: **the audit must never report health it has not
measured.** The five week outage was invisible precisely because absence of evidence was
being read as evidence of absence.
"""
from __future__ import annotations

import sqlite3

import pytest

from ops import audit
from ops.audit import FAIL, PASS, UNKNOWN, Check


def _db(tmp_path, rows):
    p = tmp_path / "research.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trials (trial_id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT)")
    c.executemany("INSERT INTO trials (stage) VALUES (?)", [(s,) for s in rows])
    c.commit()
    c.close()
    return str(p)


def test_a_crashing_check_fails_it_does_not_skip_it():
    """A check that throws must not silently disappear from the report."""
    @audit._check
    def check_explodes():
        raise RuntimeError("boom")

    c = check_explodes()
    assert c.status == UNKNOWN
    assert not c.ok
    assert "boom" in c.evidence


def test_unknown_is_not_ok():
    assert not Check("x", "q", UNKNOWN, "f").ok
    assert not Check("x", "q", FAIL, "f").ok
    assert Check("x", "q", PASS, "f").ok


def test_exit_code_is_failure_when_anything_is_unknown(monkeypatch):
    monkeypatch.setattr(audit, "ALL_CHECKS",
                        [lambda: Check("a", "q", PASS, "fine"),
                         lambda: Check("b", "q", UNKNOWN, "cannot tell")])
    monkeypatch.setattr(audit, "push", lambda checks: None)
    assert audit.main() == 1


def test_exit_code_is_success_only_when_everything_passed(monkeypatch):
    monkeypatch.setattr(audit, "ALL_CHECKS", [lambda: Check("a", "q", PASS, "fine")])
    monkeypatch.setattr(audit, "push", lambda checks: None)
    assert audit.main() == 0


def test_the_five_week_outage_is_detected(tmp_path):
    """Proposals came in, every one was skipped before testing, CI reported success."""
    db = _db(tmp_path, ["tabu"] * 18)
    c = audit.check_loop_is_learning(db_path=db)
    assert c.status == FAIL
    assert "tested none" in c.finding


def test_mostly_skipping_is_detected(tmp_path):
    db = _db(tmp_path, ["backtest"] + ["tabu"] * 19)
    c = audit.check_loop_is_learning(db_path=db)
    assert c.status == FAIL
    assert "threw away" in c.finding


def test_a_healthy_loop_passes(tmp_path):
    db = _db(tmp_path, ["backtest"] * 6 + ["tabu"] * 2)
    c = audit.check_loop_is_learning(db_path=db)
    assert c.status == PASS


def test_history_alone_is_not_evidence_the_loop_works(tmp_path):
    """Imported historical rows must not be mistaken for current activity."""
    db = _db(tmp_path, ["backfilled"] * 18)
    c = audit.check_loop_is_learning(db_path=db)
    assert c.status == UNKNOWN


def test_missing_database_is_unknown_not_pass(tmp_path):
    c = audit.check_loop_is_learning(db_path=str(tmp_path / "nope.db"))
    assert c.status == UNKNOWN


def test_paying_for_nothing_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("LAST_RUN_SPEND_USD", "4.20")
    db = _db(tmp_path, ["tabu"] * 5)
    c = audit.check_spend_is_buying_something(db_path=db)
    assert c.status == FAIL
    assert "4.20" in c.finding


def test_missing_secret_is_a_failure(monkeypatch):
    for k in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN",
              "SUPABASE_URL", "SUPABASE_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("SUPABASE_KEY")
    c = audit.check_secrets_present()
    assert c.status == FAIL
    assert "SUPABASE_KEY" in c.evidence


def test_a_workflow_that_cannot_fail_is_flagged(tmp_path):
    wf = tmp_path / "wf.yml"
    wf.write_text("jobs:\n  run:\n    steps:\n      - run: |\n          set +e\n          exit 0\n")
    c = audit.check_ci_can_fail(workflow=str(wf))
    assert c.status == FAIL
    assert "always reports success" in c.finding


def test_report_names_the_number_wrong():
    checks = [Check("a", "q1", PASS, "fine"), Check("b", "q2", FAIL, "broken"),
              Check("c", "q3", UNKNOWN, "unclear")]
    txt = audit.format_report(checks)
    assert "2 of 3 things are wrong" in txt
    assert "broken" in txt and "unclear" in txt


@pytest.mark.parametrize("fn", audit.ALL_CHECKS)
def test_every_check_returns_a_plain_sentence(fn):
    """No jargon on the audit's own output: this is read by people who do not trade."""
    c = fn()
    assert c.finding and c.finding[0].isupper() and c.finding.rstrip().endswith(".")
    for jargon in ("sharpe", "deflated", "p-value", "pgrst", "traceback"):
        assert jargon not in c.finding.lower()
