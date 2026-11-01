"""The engine's heartbeat: one loop that holds the broker session in turns, forever.

One broker session per account, so everything that talks to the broker takes turns here,
once an hour:

  1. record XRPUSD depth for E03 (until 120 hours), restarting the recorder whenever it goes
     silent for 2 minutes (it lost its connection unnoticed for up to 50 minutes on
     2026-09-22); once E03 has its data, just wait;
  2. publish the live state (balance, positions, closes) to the dashboard;
  3. run one trader step (scripts/trader_step.py: every live instrument, see INSTRUMENTS);
  4. when E03 reaches 120 hours, score it, record the verdict and push it.

A Windows scheduled task starts this at logon and re-launches it every 15 minutes; a lock file
makes any second copy exit at once, so that doubles as a watchdog. The cloud hourly job is
paused while this runs, because this loop does its work.

    python -m scripts.engine_loop
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time

from config import settings
from scripts.record_e03 import E03_DB, TARGET_HOURS, hours_recorded

ROOT = os.path.join(settings.ARTIFACT_ROOT, "engine")
LOCK = os.path.join(ROOT, "engine.lock")
HEARTBEAT = os.path.join(ROOT, "heartbeat.json")
LOG = os.path.join(ROOT, "engine.log")
SLOT_S, STALL_S = 52 * 60, 120
PY = sys.executable.replace("pythonw.exe", "python.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z  {msg}"
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def beat(phase: str) -> None:
    with open(HEARTBEAT, "w", encoding="utf-8") as fh:
        json.dump({"ts": time.time(), "phase": phase, "pid": os.getpid()}, fh)


def _alive(pid: int) -> bool:
    # The PID must belong to a python process. After a reboot Windows hands old PIDs to
    # unrelated processes (2026-09-25: the stale supervisor PID became a svchost, so the
    # supervisor thought it was already running, exited 0, and the engine stayed down ~19 h).
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    for line in r.stdout.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) > 1 and cols[1] == str(pid) and cols[0].lower().startswith("python"):
            return True
    return False


def acquire_lock() -> bool:
    try:
        with open(LOCK, encoding="utf-8") as fh:
            pid = int(fh.read().strip() or 0)
        if pid and pid != os.getpid() and _alive(pid):
            return False
    except (OSError, ValueError):
        pass
    with open(LOCK, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    return True


def run(args: list[str], timeout: int, env: dict | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run([PY, *args], capture_output=True, text=True, timeout=timeout,
                              env=env, creationflags=NO_WINDOW, check=False)
    except subprocess.TimeoutExpired:
        log(f"{args[1] if len(args) > 1 else args} timed out")
        return None


def _last_depth_ts() -> float:
    try:
        with sqlite3.connect(E03_DB) as c:
            v = c.execute("SELECT MAX(ts_utc) FROM depth_quotes WHERE symbol='XRPUSD'").fetchone()[0]
        return float(v or 0)
    except sqlite3.Error:
        return 0.0


_forecast: dict = {"proc": None, "hour": None}


def maybe_forecast() -> None:
    """E16: start the hourly forecast cycle once per UTC hour, from minute 1, in the
    background; never two at once. The cycle itself refuses an hour already recorded."""
    hour = int(time.time()) // 3600
    p = _forecast["proc"]
    if p is not None and p.poll() is None:
        return
    if _forecast["hour"] == hour or time.time() - hour * 3600 < 60:
        return
    _forecast["hour"] = hour
    out = open(os.path.join(ROOT, "forecast.log"), "a", encoding="utf-8")
    _forecast["proc"] = subprocess.Popen([PY, "-m", "forecast.cycle"], stdout=out, stderr=out,
                                         creationflags=NO_WINDOW)
    log("forecast cycle started")


def record_slot() -> None:
    """Record for SLOT_S, restarting the recorder whenever it stalls."""
    env = dict(os.environ, TELEMETRY_DB=E03_DB)
    end = time.time() + SLOT_S
    while time.time() < end - 60:
        left = int(end - time.time())
        p = subprocess.Popen([PY, "-m", "telemetry.logger", "--symbols", "XRPUSD", "--depth",
                              "--duration", str(left), "--no-snapshot"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=NO_WINDOW)
        started = time.time()
        while p.poll() is None:
            time.sleep(30)
            beat("recording")
            maybe_forecast()
            if time.time() - started > STALL_S and time.time() - _last_depth_ts() > STALL_S:
                log("recorder silent for 2 minutes; restarting it")
                p.kill()
                p.wait(timeout=30)
                break
        time.sleep(5)


def wait_slot() -> None:
    end = time.time() + SLOT_S
    while time.time() < end:
        time.sleep(60)
        beat("waiting")
        maybe_forecast()


def finalize_e03() -> None:
    """Score E03 once, record the verdict in the register, commit and push."""
    out = "docs/results/E03-book-imbalance.json"
    if os.path.exists(out):
        return
    r = run(["-m", "scripts.e03_book"], timeout=3600)
    if r is None or not os.path.exists(out):
        log(f"E03 scoring failed: {(r.stdout + r.stderr)[-300:] if r else 'timeout'}")
        return
    res = json.load(open(out, encoding="utf-8"))
    reg_path = "docs/programme/register.json"
    reg = json.load(open(reg_path, encoding="utf-8"))
    for e in reg["experiments"]:
        if e["id"] == "E03":
            e["result"], e["verdict"] = out, res["verdict"]
            e["summary"] = (
                "Order-book pressure on XRP " +
                ("predicted the next minute well enough to pay for trading."
                 if res["verdict"] == "PASS" else
                 "did not make money after crossing the spread twice.") +
                f" {res['trades']} simulated trades over {res['hours_recorded']:.0f} hours.")
    with open(reg_path, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2)
        fh.write("\n")
    msg = (f"E03 scored automatically: {res['verdict']}\n\n{res['trades']} trades, mean net "
           f"{res['mean_net_per_trade']:.6f} per trade, t {res['t_stat']:.2f}, rank correlation "
           f"{res['rank_correlation']:.4f}.\n\nCommitted by scripts/engine_loop.py.")
    for cmd in (["git", "add", out, reg_path], ["git", "commit", "-m", msg],
                ["git", "push", "-q", "origin", "main"]):
        subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, check=False)
    log(f"E03 scored {res['verdict']} and pushed")


def main() -> int:
    os.makedirs(ROOT, exist_ok=True)
    if not acquire_lock():
        return 0
    log(f"engine loop started, pid {os.getpid()}")
    subprocess.run(["gh", "workflow", "disable", "live_state.yml"], capture_output=True,
                   creationflags=NO_WINDOW, check=False)
    try:
        while True:
            h = hours_recorded()
            if h < TARGET_HOURS:
                beat("recording")
                record_slot()
            else:
                beat("waiting")
                finalize_e03()
                wait_slot()
            maybe_forecast()
            beat("publishing")
            r = run(["-m", "scripts.push_live_state"], timeout=180)
            log("live state published" if r and r.returncode == 0 else "live state push failed")
            beat("trading")
            r = run(["-m", "scripts.trader_step"], timeout=900)
            if r is not None and r.stdout.strip():
                log("trader: " + r.stdout.strip().splitlines()[-1][:400])
            log(f"cycle done; E03 {hours_recorded():.1f} h recorded")
    finally:
        subprocess.run(["gh", "workflow", "enable", "live_state.yml"], capture_output=True,
                       creationflags=NO_WINDOW, check=False)
        log("engine loop stopped; cloud hourly job re-enabled")


if __name__ == "__main__":
    raise SystemExit(main())
