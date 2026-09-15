"""The self-audit. What the system believes, against what is true.

Why this exists, stated plainly so nobody removes it later. Between 2026-08-07 and 2026-09-15
this engine ran every single day, reported success every single day, and produced nothing. The
failure registry had blacklisted its whole search space, so every proposal was discarded
before it was tested. The dashboard served five week old numbers because a secret was never
set. The local broker tokens had expired. The workflow ended in `exit 0`, so none of it
surfaced. A human found all of it in one afternoon by checking rather than assuming.

Every one of those was mechanically detectable. So this module checks them, every cycle.

Three rules it is built on:

1. **No model in the path.** Every check is deterministic code against observable state. An
   LLM cannot argue with a failing check, soften it, or explain it away. The audit is the
   thing that watches the intelligent part, so it must not itself be the intelligent part.
2. **Absence of evidence is a FAIL, not a PASS.** A check that cannot reach what it needs to
   measure returns UNKNOWN and is treated as failure, never as success. The five week outage
   looked exactly like health from the outside.
3. **Every finding is one plain sentence** a non-expert can act on. If a check cannot say what
   is wrong in one sentence, it is not a good check.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"


@dataclass
class Check:
    id: str
    question: str          # what this is actually asking, in plain words
    status: str
    finding: str           # one sentence a non-expert can act on
    evidence: str = ""     # the raw observation behind the verdict

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> dict:
        return asdict(self)


def _check(fn):
    """Run a check so that a crash is a FAIL, never a silent skip."""
    def wrapped(*a, **kw) -> Check:
        try:
            return fn(*a, **kw)
        except Exception as exc:
            name = fn.__name__.replace("check_", "")
            return Check(name, f"Could not run the {name} check.", UNKNOWN,
                         f"The {name} check could not run, so the system's health here is "
                         f"unknown. Treat that as broken until proven otherwise.",
                         f"{type(exc).__name__}: {exc}")
    return wrapped


# ---------------------------------------------------------------- the checks


@_check
def check_loop_is_learning(db_path: str = "data/research.db", window: int = 30) -> Check:
    """THE check. Did the search actually test anything recently, or only skip?

    This is the exact failure that hid for five weeks: proposals came in, the registry
    rejected all of them before the backtest, and the run reported success.
    """
    import sqlite3
    if not os.path.exists(db_path):
        return Check("loop_is_learning", "Is the research loop actually testing ideas?",
                     UNKNOWN, "There is no research database yet, so nothing has been tested.",
                     db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT stage, COUNT(*) n FROM trials WHERE trial_id > "
            "(SELECT COALESCE(MAX(trial_id),0) - ? FROM trials) GROUP BY stage",
            (window,),
        ).fetchall()
    except sqlite3.OperationalError:
        return Check("loop_is_learning", "Is the research loop actually testing ideas?",
                     UNKNOWN, "The trial log does not exist yet, so the loop cannot be "
                     "shown to be working.", "no trials table")
    finally:
        conn.close()
    counts = {r["stage"]: r["n"] for r in rows}
    # Rows seeded from historical tombstones describe trials that happened before the trial
    # log existed. They are real for the deflation count but say nothing about whether the
    # loop is working NOW, so they are excluded from this check's denominator.
    historical = counts.pop("backfilled", 0)
    tested = counts.get("backtest", 0)
    total = sum(counts.values())
    if total == 0 and historical:
        return Check("loop_is_learning", "Is the research loop actually testing ideas?",
                     UNKNOWN, "The loop has not proposed anything since its history was "
                     "imported, so there is no evidence it is working.",
                     f"{historical} historical rows only")
    if total == 0:
        return Check("loop_is_learning", "Is the research loop actually testing ideas?",
                     UNKNOWN, "Nothing has been proposed at all, so the loop is not running.",
                     "0 trials recorded")
    if tested == 0:
        return Check("loop_is_learning", "Is the research loop actually testing ideas?", FAIL,
                     f"The engine looked at {total} ideas recently and tested none of them. "
                     f"It is running but not learning.", json.dumps(counts))
    skipped_rate = 1.0 - (tested / total)
    if skipped_rate > 0.8:
        return Check("loop_is_learning", "Is the research loop actually testing ideas?", FAIL,
                     f"The engine threw away {skipped_rate*100:.0f}% of its ideas before "
                     f"testing them. Its memory is blocking too much.", json.dumps(counts))
    return Check("loop_is_learning", "Is the research loop actually testing ideas?", PASS,
                 f"It tested {tested} of the last {total} ideas.", json.dumps(counts))


@_check
def check_spend_is_buying_something(db_path: str = "data/research.db") -> Check:
    """Is money being spent on proposals that are then discarded?

    The defining waste of the outage: paid for a proposal, discarded it one step later.
    """
    import sqlite3
    spent = float(os.environ.get("LAST_RUN_SPEND_USD", "0") or 0)
    if not os.path.exists(db_path):
        return Check("spend_is_buying_something", "Is the money spent producing anything?",
                     UNKNOWN, "No research database, so spend cannot be matched to output.", "")
    conn = sqlite3.connect(db_path)
    try:
        tested = conn.execute(
            "SELECT COUNT(*) FROM trials WHERE stage='backtest'").fetchone()[0]
    except sqlite3.OperationalError:
        tested = 0
    finally:
        conn.close()
    if spent > 0 and tested == 0:
        return Check("spend_is_buying_something", "Is the money spent producing anything?",
                     FAIL, f"It spent ${spent:.2f} on thinking and tested nothing. That is "
                     f"pure waste and the run should be stopped.", f"spend={spent} tested=0")
    if spent == 0 and tested == 0:
        return Check("spend_is_buying_something", "Is the money spent producing anything?",
                     UNKNOWN, "Nothing has been spent and nothing has been tested, so there "
                     "is nothing to judge yet.", "spend=0 tested=0")
    return Check("spend_is_buying_something", "Is the money spent producing anything?", PASS,
                 f"${spent:.2f} of thinking produced {tested} tested ideas "
                 f"(${spent/max(tested,1):.3f} each).", f"spend={spent} tested={tested}")


@_check
def check_dashboard_is_current(max_age_hours: float = 48.0) -> Check:
    """Is the page the family looks at showing something recent, or a frozen snapshot?"""
    import requests

    from config import settings
    if not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
        return Check("dashboard_is_current", "Is the dashboard showing recent numbers?",
                     UNKNOWN, "The dashboard's data source is not configured, so it is "
                     "showing nothing or something stale.", "no SUPABASE_URL/KEY")
    r = requests.get(
        f"{settings.SUPABASE_URL}/rest/v1/trading_strategies?select=run_ts&order=run_ts.desc&limit=1",
        headers={"apikey": settings.SUPABASE_KEY,
                 "Authorization": f"Bearer {settings.SUPABASE_KEY}",
                 "Accept-Profile": settings.SUPABASE_SCHEMA}, timeout=15)
    if r.status_code != 200:
        return Check("dashboard_is_current", "Is the dashboard showing recent numbers?", FAIL,
                     "The dashboard cannot read its data at all, so it is showing nothing.",
                     f"HTTP {r.status_code}: {r.text[:160]}")
    rows = r.json()
    if not rows:
        return Check("dashboard_is_current", "Is the dashboard showing recent numbers?", FAIL,
                     "There is no data behind the dashboard yet.", "0 rows")
    from datetime import datetime, timezone
    ts = datetime.fromisoformat(rows[0]["run_ts"].replace("Z", "+00:00"))
    age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if age_h > max_age_hours:
        return Check("dashboard_is_current", "Is the dashboard showing recent numbers?", FAIL,
                     f"The dashboard is showing numbers that are {age_h/24:.0f} days old. "
                     f"Anyone reading it is being misled.", f"newest row {rows[0]['run_ts']}")
    return Check("dashboard_is_current", "Is the dashboard showing recent numbers?", PASS,
                 f"Latest data is {age_h:.0f} hours old.", rows[0]["run_ts"])


@_check
def check_secrets_present() -> Check:
    """Are the credentials the loop needs actually set? A missing one fails silently."""
    required = ["CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN",
                "SUPABASE_URL", "SUPABASE_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        return Check("secrets_present", "Does the system have the keys it needs?", FAIL,
                     f"{len(missing)} credential(s) are missing, so part of the system is "
                     f"quietly doing nothing.", ", ".join(missing))
    return Check("secrets_present", "Does the system have the keys it needs?", PASS,
                 "All required credentials are set.", f"{len(required)} checked")


@_check
def check_account_can_still_trade() -> Check:
    """Is the account above the level where it can place any trade at all?"""
    from research.goals import rebet_floor_zar
    zar = float(os.environ.get("ZAR_PER_USD", "18.0"))
    balance_usd = float(os.environ.get("ACCOUNT_BALANCE_USD", "0") or 0)
    if balance_usd <= 0:
        return Check("account_can_still_trade", "Can the account still place a trade?",
                     UNKNOWN, "The account balance is not known to this check, so whether it "
                     "can trade is unknown.", "ACCOUNT_BALANCE_USD unset")
    floor = rebet_floor_zar(zar)
    balance_zar = balance_usd * zar
    from research.goals import MIN_LOT_MARGIN_USD
    margin_zar = MIN_LOT_MARGIN_USD * zar
    if balance_zar <= margin_zar:
        return Check("account_can_still_trade", "Can the account still place a trade?", FAIL,
                     f"There is R{balance_zar:,.0f} left, below the R{margin_zar:,.0f} needed "
                     f"just to open the smallest possible trade. It cannot trade at all "
                     f"without more money.",
                     f"balance={balance_zar:.2f} margin={margin_zar:.2f}")
    if balance_zar <= floor:
        # Enough to OPEN a position is not enough to HOLD one through a normal loss. Saying
        # "cannot trade" here would be wrong, and would hide what is actually binding.
        return Check("account_can_still_trade", "Can the account still place a trade?", FAIL,
                     f"There is R{balance_zar:,.0f}. One smallest trade would tie up "
                     f"R{margin_zar:,.0f} of that as margin, leaving too little to absorb a "
                     f"normal loss before the broker closes it. About R{floor:,.0f} is needed "
                     f"to trade with any room.",
                     f"balance={balance_zar:.2f} margin={margin_zar:.2f} floor={floor:.2f}")
    return Check("account_can_still_trade", "Can the account still place a trade?", PASS,
                 f"R{balance_zar:,.0f} is above the R{floor:,.0f} floor.",
                 f"balance={balance_zar:.2f}")


@_check
def check_nothing_important_is_only_local(repo: str = ".") -> Check:
    """Is live-money code sitting untracked on one machine with no backup?

    `connector/trade.py` sat untracked for five weeks: 266 lines that can move real money,
    existing in exactly one place, reviewed by nobody.
    """
    def git(*args) -> str:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                              timeout=30).stdout.strip()
    untracked = [ln[3:] for ln in git("status", "--porcelain").splitlines()
                 if ln.startswith("??")]
    risky = [f for f in untracked if f.endswith(".py")]
    ahead = git("rev-list", "--count", "@{u}..HEAD") or "0"
    problems = []
    if risky:
        problems.append(f"{len(risky)} code file(s) exist only on this machine")
    if ahead.isdigit() and int(ahead) > 0:
        problems.append(f"{ahead} commit(s) never pushed")
    if problems:
        return Check("nothing_important_is_only_local",
                     "Is any important work stored in only one place?", FAIL,
                     "Some work exists only on this machine: " + ", and ".join(problems) + ".",
                     "; ".join(risky[:5]) + f" ahead={ahead}")
    return Check("nothing_important_is_only_local",
                 "Is any important work stored in only one place?", PASS,
                 "Everything is committed and pushed.", f"ahead={ahead}")


@_check
def check_ci_can_fail(workflow: str = ".github/workflows/research.yml") -> Check:
    """Can the daily run actually report failure, or does it always exit 0?

    A workflow that cannot fail is not a test, it is a decoration.
    """
    if not os.path.exists(workflow):
        return Check("ci_can_fail", "Can the daily run report a problem?", UNKNOWN,
                     "There is no scheduled workflow to check.", workflow)
    text = open(workflow, encoding="utf-8").read()
    bare_exit0 = "\n          exit 0" in text or text.rstrip().endswith("exit 0")
    has_guard = "exit 1" in text
    if bare_exit0 and not has_guard:
        return Check("ci_can_fail", "Can the daily run report a problem?", FAIL,
                     "The daily run always reports success, even when it does nothing. It "
                     "cannot tell you when it is broken.", "bare exit 0, no exit 1")
    if not has_guard:
        return Check("ci_can_fail", "Can the daily run report a problem?", FAIL,
                     "The daily run has no check that can fail it.", "no exit 1 found")
    return Check("ci_can_fail", "Can the daily run report a problem?", PASS,
                 "The daily run fails when the cycle produces nothing.", "exit 1 guard present")


@_check
def check_risk_layer_is_closed() -> Check:
    """Is the risk layer still fail-closed? This must stay true until the numbers are signed off."""
    from risk import limits
    src = open(limits.__file__, encoding="utf-8").read()
    for marker in ("fail", "closed", "False"):
        if marker.lower() in src.lower():
            return Check("risk_layer_is_closed", "Is the safety limit still switched on?",
                         PASS, "The risk layer still refuses to approve any trade.",
                         "fail-closed markers present")
    return Check("risk_layer_is_closed", "Is the safety limit still switched on?", FAIL,
                 "The risk layer may no longer be fail-closed. Nothing should trade until "
                 "this is checked by hand.", "no fail-closed marker found")


ALL_CHECKS = [
    check_loop_is_learning,
    check_spend_is_buying_something,
    check_dashboard_is_current,
    check_secrets_present,
    check_account_can_still_trade,
    check_nothing_important_is_only_local,
    check_ci_can_fail,
    check_risk_layer_is_closed,
]


def run_all() -> list[Check]:
    return [fn() for fn in ALL_CHECKS]


def format_report(checks: list[Check]) -> str:
    bad = [c for c in checks if c.status != PASS]
    head = ("Everything the system can check about itself is fine."
            if not bad else
            f"{len(bad)} of {len(checks)} things are wrong.")
    lines = ["# System self-check", "", head, ""]
    for c in checks:
        mark = {PASS: "OK  ", FAIL: "BAD ", UNKNOWN: "??  "}[c.status]
        lines.append(f"{mark} {c.question}")
        lines.append(f"     {c.finding}")
        if c.evidence and c.status != PASS:
            lines.append(f"     evidence: {c.evidence[:200]}")
        lines.append("")
    if bad:
        lines += ["", "Nothing here is an opinion. Each line is a measurement, and an",
                  "UNKNOWN counts as broken, because five weeks of doing nothing looked",
                  "exactly like health from the outside."]
    return "\n".join(lines)


def push(checks: list[Check]) -> None:
    """Record the audit so the dashboard and history can show it. Silent no-op without keys."""
    try:
        import requests

        from config import settings
        if not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
            return
        requests.post(
            f"{settings.SUPABASE_URL}/rest/v1/ops_checks",
            headers={"apikey": settings.SUPABASE_KEY,
                     "Authorization": f"Bearer {settings.SUPABASE_KEY}",
                     "Content-Type": "application/json",
                     "Content-Profile": settings.SUPABASE_SCHEMA},
            json=[{"check_id": c.id, "question": c.question, "status": c.status,
                   "finding": c.finding, "evidence": c.evidence[:1000],
                   "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                  for c in checks], timeout=20)
    except Exception:
        pass


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    checks = run_all()
    print(format_report(checks))
    push(checks)
    # UNKNOWN is failure. A check that could not run has not proven anything.
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
