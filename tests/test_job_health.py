from datetime import datetime, timezone

from ops import job_health as jh

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc).timestamp()


def row(job, status, ts):
    return {"check_id": f"job:{job}", "status": status, "ran_at": ts, "finding": "x"}


def test_latest_record_decides():
    rows = [row("research", "FAIL", "2026-10-20T05:10:00Z"),
            row("research", "OK", "2026-10-21T05:10:00Z")]
    assert jh.problems(rows, NOW) == []


def test_failure_is_reported():
    rows = [row("research", "OK", "2026-10-20T05:10:00Z"),
            row("research", "FAIL", "2026-10-21T05:10:00Z")]
    p = jh.problems(rows, NOW)
    assert [x["job"] for x in p] == ["research"] and p[0]["why"] == "failed"


def test_silence_is_a_failure_for_scheduled_jobs_only():
    rows = [row("research", "OK", "2026-10-18T05:10:00Z"),
            row("databricks-run", "OK", "2026-09-01T00:00:00Z")]
    p = jh.problems(rows, NOW)
    assert [x["job"] for x in p] == ["research"] and p[0]["why"] == "overdue"


def test_other_checks_are_ignored():
    assert jh.problems([{"check_id": "live_money_stays_gated", "status": "FAIL",
                         "ran_at": "2026-10-21T05:00:00Z"}], NOW) == []


def test_main_never_fails_the_job(monkeypatch):
    for k in ("SUPABASE_URL", "SUPABASE_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(jh, "record", lambda *a, **k: False)
    assert jh.main(["--job", "research", "--status", "failure"]) == 0
