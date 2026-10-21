"""Copy the engine's data to Databricks, so research can run there instead of on this PC.

Snapshots each SQLite database with SQLite's online backup (consistent even while the engine
is writing to it), then uploads the snapshots and the decision log to the Unity Catalog volume
/Volumes/workspace/trading_engine/raw/. Uses this PC's Databricks CLI login (profile DEFAULT).

Runs once a day from scripts/trader_step.py, after the live check. Uploading moves no money and
sends no credentials: the broker tokens and the live secret never leave this PC.

    python -m scripts.upload_to_databricks
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time

VOLUME = "dbfs:/Volumes/workspace/trading_engine/raw"
STAGING = os.environ.get("DBX_STAGING", r"T:\making-money\dbx_upload")
DATABASES = ["data/market.db", "data/telemetry.db", "data/trade_log.db", "data/research.db"]
FILES = ["data/engine_decisions.jsonl", "data/spread_summary.json", "data/swaps.json"]


def cli() -> str:
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "clouds", "databricks",
                       "databricks.exe")
    return exe if os.path.exists(exe) else (shutil.which("databricks") or "databricks")


def snapshot(src: str, dst: str) -> None:
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)


def upload(local: str) -> bool:
    r = subprocess.run([cli(), "fs", "cp", local, f"{VOLUME}/{os.path.basename(local)}",
                        "--overwrite"], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print(f"upload failed for {local}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.returncode == 0


def main() -> int:
    os.makedirs(STAGING, exist_ok=True)
    ok = True
    t0 = time.time()
    for db in DATABASES:
        if not os.path.exists(db):
            continue
        dst = os.path.join(STAGING, os.path.basename(db))
        snapshot(db, dst)
        ok &= upload(dst)
    for f in FILES:
        if os.path.exists(f):
            ok &= upload(f)
    stamp = os.path.join(STAGING, "uploaded_at.txt")
    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    ok &= upload(stamp)
    print(f"{'uploaded' if ok else 'upload had failures'} in {time.time() - t0:.0f} s")
    # Same-day alert (dashboard banner). It failed silently into a log file for days when the
    # Databricks sign-in on this PC expired.
    from ops.job_health import record
    record("pc-dbx-upload", ok, "uploaded" if ok else
           "upload failed: usually the Databricks sign-in on the PC expired "
           "(databricks auth login --profile DEFAULT)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
