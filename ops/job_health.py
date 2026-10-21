"""Same-day alerts for the engine's scheduled jobs.

Why: the daily research run failed on 18, 19 and 20 October 2026 and the weekly Databricks
job on 19 October, and nobody saw it for three days. A failure that sits in a log is the same
as no failure to the owner. So every scheduled job ends by calling this module, which

  1. records `job:<name>` OK or FAIL in `making_money.ops_checks` (the dashboard reads it and
     shows a red banner while any job's latest record is FAIL or the job is overdue), and
  2. in GitHub Actions, opens one issue per failing job (label `job-failure`). GitHub emails
     the repository owner about new issues and comments the same day. A later success closes
     the issue, so an open issue always means "still broken".

Standard library only: workflows that do not install the package can still run it as
`python ops/job_health.py ...`. It never raises: an alert that crashes the job it reports on
would hide the original failure.

    python ops/job_health.py --job research --status failure --url <run url>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

#: How often each job is meant to run, in hours. A job whose latest record is older than this
#: (plus slack) is reported overdue: a job that silently stopped running has also failed.
CADENCE_H = {
    "research": 24 + 2,            # daily 05:00 UTC
    "reading-room": 7 * 24 + 24,   # weekly, Sunday
    "external-data": 7 * 24 + 24,  # weekly, Monday 03:00 UTC
    "pc-dbx-upload": 24 + 4,       # daily from the engine PC
    "learning-fleet": 3,           # hourly from the engine PC
}
#: Jobs that run on demand: a failure alerts, silence does not.
ON_DEMAND = {"databricks-run"}
LABEL = "job-failure"
SCHEMA = os.environ.get("SUPABASE_SCHEMA", "making_money")


def _request(method: str, url: str, headers: dict, body=None, timeout: int = 20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def record(job: str, ok: bool, detail: str = "", url: str = "") -> bool:
    """Write one `job:<name>` row to ops_checks. Returns False (never raises) without keys."""
    sb_url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", "")
    if not (sb_url and key):
        try:
            from config import settings          # PC: keys come from .env via settings
            sb_url, key = settings.SUPABASE_URL, settings.SUPABASE_KEY
        except Exception:                        # noqa: BLE001
            pass
    if not (sb_url and key):
        return False
    row = {"check_id": f"job:{job}", "question": f"Did the {job} job succeed?",
           "status": "OK" if ok else "FAIL", "finding": (detail or ("ran" if ok else "failed"))[:500],
           "evidence": url[:1000], "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        _request("POST", f"{sb_url}/rest/v1/ops_checks",
                 {"apikey": key, "Authorization": f"Bearer {key}",
                  "Content-Type": "application/json", "Content-Profile": SCHEMA}, [row])
        return True
    except Exception as exc:                     # noqa: BLE001
        print(f"job_health: could not record {job}: {type(exc).__name__}", file=sys.stderr)
        return False


def issue_title(job: str) -> str:
    return f"Job failing: {job}"


def github_issue(job: str, ok: bool, url: str = "") -> str:
    """Open/comment (failure) or close (success) the job's issue. Returns what it did."""
    token, repo = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"), \
        os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return "skipped (not in GitHub Actions)"
    api = f"https://api.github.com/repos/{repo}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
         "Content-Type": "application/json"}
    try:
        q = urllib.parse.urlencode({"state": "open", "labels": LABEL, "per_page": 50})
        found = [i for i in (_request("GET", f"{api}/issues?{q}", h) or [])
                 if i.get("title") == issue_title(job)]
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if ok:
            for i in found:
                _request("POST", f"{api}/issues/{i['number']}/comments", h,
                         {"body": f"Fixed: {job} succeeded at {stamp}. {url}"})
                _request("PATCH", f"{api}/issues/{i['number']}", h,
                         {"state": "closed", "state_reason": "completed"})
            return f"closed {len(found)}" if found else "nothing open"
        body = (f"The **{job}** job failed at {stamp}.\n\nRun: {url}\n\n"
                "This issue closes itself when the job next succeeds. While it is open the "
                "dashboard shows a red banner.")
        if found:
            _request("POST", f"{api}/issues/{found[0]['number']}/comments", h, {"body": body})
            return f"commented on #{found[0]['number']}"
        made = _request("POST", f"{api}/issues", h,
                        {"title": issue_title(job), "body": body, "labels": [LABEL]})
        return f"opened #{made.get('number')}"
    except Exception as exc:                     # noqa: BLE001
        return f"issue step failed: {type(exc).__name__}"


def problems(rows: list[dict], now: float | None = None) -> list[dict]:
    """From ops_checks rows (any order), the jobs that need attention now.

    A job needs attention when its LATEST record is FAIL, or when it has a cadence and its
    latest record is older than that cadence. Pure function: the dashboard and tests use it.
    """
    now = time.time() if now is None else now
    latest: dict[str, dict] = {}
    for r in rows:
        cid = r.get("check_id") or ""
        if not cid.startswith("job:"):
            continue
        job = cid[4:]
        if job not in latest or (r.get("ran_at") or "") > (latest[job].get("ran_at") or ""):
            latest[job] = r
    out = []
    for job, r in sorted(latest.items()):
        try:
            ts = datetime.fromisoformat(str(r.get("ran_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            ts = 0.0
        age_h = (now - ts) / 3600.0
        if r.get("status") == "FAIL":
            out.append({"job": job, "why": "failed", "age_h": round(age_h, 1),
                        "detail": r.get("finding") or "", "url": r.get("evidence") or ""})
        elif job in CADENCE_H and job not in ON_DEMAND and age_h > CADENCE_H[job]:
            out.append({"job": job, "why": "overdue", "age_h": round(age_h, 1),
                        "detail": f"last ran {age_h:.0f} hours ago", "url": ""})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--status", required=True, help="success or failure (GitHub job.status)")
    ap.add_argument("--url", default="")
    ap.add_argument("--detail", default="")
    a = ap.parse_args(argv)
    ok = a.status.lower() == "success"
    wrote = record(a.job, ok, a.detail, a.url)
    did = github_issue(a.job, ok, a.url)
    print(f"job {a.job}: {'OK' if ok else 'FAIL'}; recorded={wrote}; issue: {did}")
    return 0          # never fail the job because of the alert itself


if __name__ == "__main__":
    raise SystemExit(main())
