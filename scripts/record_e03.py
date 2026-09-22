"""Record E03's evaluation data (XRPUSD depth) without starving the dashboard.

One broker session per account: a recorder holding it for five days would freeze the hourly
dashboard job and stop the close of an open trade from being logged. So this loop records for
55 minutes, releases the session, publishes the live state itself (the job the cloud would
have run), and repeats. The cloud hourly job is paused while this runs and re-enabled on exit.

Data goes to T: (settings.ARTIFACT_ROOT), not C:, which had 2 GB free on 2026-09-22.

    python -m scripts.record_e03            # runs until 120 hours are recorded
    python -m scripts.record_e03 --status   # hours recorded so far
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time

from config import settings

E03_DB = os.path.join(settings.ARTIFACT_ROOT, "e03", "telemetry_e03.db")
TARGET_HOURS = 120.0
RECORD_S = 55 * 60
PY = sys.executable


def hours_recorded(db: str = E03_DB) -> float:
    """Distinct minutes with XRPUSD depth rows, in hours: gaps are not counted as data."""
    if not os.path.exists(db):
        return 0.0
    with sqlite3.connect(db) as c:
        try:
            n = c.execute("SELECT COUNT(DISTINCT CAST(ts_utc / 60 AS INTEGER)) FROM depth_quotes "
                          "WHERE symbol='XRPUSD'").fetchone()[0]
        except sqlite3.OperationalError:
            return 0.0
    return n / 60.0


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z  {msg}"
    print(line, flush=True)
    with open(os.path.join(os.path.dirname(E03_DB), "record.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _gh(*args: str) -> None:
    subprocess.run(["gh", "workflow", *args, "live_state.yml"], check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(E03_DB), exist_ok=True)
    if a.status:
        print(f"{hours_recorded():.1f} of {TARGET_HOURS:.0f} hours recorded -> {E03_DB}")
        return 0
    env = dict(os.environ, TELEMETRY_DB=E03_DB)
    _gh("disable")
    _log("cloud hourly job paused; recording starts")
    try:
        while (h := hours_recorded()) < TARGET_HOURS:
            _log(f"{h:.1f} h recorded; recording 55 min")
            try:
                subprocess.run([PY, "-m", "telemetry.logger", "--symbols", "XRPUSD", "--depth",
                                "--duration", str(RECORD_S), "--no-snapshot"],
                               env=env, timeout=RECORD_S + 300, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                _log("recorder overran its slot and was stopped")
            try:
                r = subprocess.run([PY, "-m", "scripts.push_live_state"], timeout=180,
                                   capture_output=True, text=True, check=False)
                _log("live state published" if r.returncode == 0
                     else f"live state push failed: {r.stderr[-200:]}")
            except subprocess.TimeoutExpired:
                _log("live state push timed out")
        _log(f"done: {hours_recorded():.1f} h recorded")
    finally:
        _gh("enable")
        _log("cloud hourly job re-enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
