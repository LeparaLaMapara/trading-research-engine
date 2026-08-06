"""Render background-worker entrypoint: run the research engine on a schedule.

Each cycle: fetch fresh bars, optionally log a bounded telemetry window, then run the
Claude+Gemini council + backtest experiment for every symbol. All data lives on the mounted
persistent disk (the repo's data/ dir), so the Failure Registry and the agent-calibration
scoreboard ACCUMULATE across cycles instead of resetting.

Each reactor-based step (bars, telemetry) runs as a SUBPROCESS because Twisted's reactor is
not restartable within a single long-lived process. This script imports no engine packages;
it only shells out to `python -m <module>`.

Config via env vars (all optional):
  RESEARCH_SYMBOLS   comma list (default EURUSD,USDJPY,XAUUSD)
  RESEARCH_PERIOD    default H1
  RESEARCH_ROUNDS    default 6
  RESEARCH_INTERVAL_S seconds between cycles (default 86400 = daily)
  BARS_DAYS          history depth to fetch (default 180)
  TELEMETRY_WINDOW_S bounded telemetry logging per cycle (default 0 = skip)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

SYMBOLS = [s.strip().upper() for s in
           os.environ.get("RESEARCH_SYMBOLS", "EURUSD,USDJPY,XAUUSD").split(",") if s.strip()]
PERIOD = os.environ.get("RESEARCH_PERIOD", "H1")
ROUNDS = os.environ.get("RESEARCH_ROUNDS", "6")
INTERVAL = int(os.environ.get("RESEARCH_INTERVAL_S", "86400"))
BARS_DAYS = os.environ.get("BARS_DAYS", "180")
TELEMETRY_WINDOW = int(os.environ.get("TELEMETRY_WINDOW_S", "0"))


def run(module_args: list[str], timeout: int) -> None:
    print(f"$ python -m {' '.join(module_args)}", flush=True)
    try:
        subprocess.run([sys.executable, "-m", *module_args], timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"(timed out after {timeout}s)", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"(step failed: {exc})", file=sys.stderr, flush=True)


def cycle() -> None:
    for sym in SYMBOLS:
        run(["market.bars", "--symbol", sym, "--period", PERIOD, "--days", BARS_DAYS], 180)
    if TELEMETRY_WINDOW > 0:
        run(["telemetry.logger", "--duration", str(TELEMETRY_WINDOW)], TELEMETRY_WINDOW + 90)
    for sym in SYMBOLS:
        run(["research.experiment", "--symbol", sym, "--period", PERIOD, "--rounds", ROUNDS], 1800)


def main() -> None:
    print(f"scheduler up. symbols={SYMBOLS} period={PERIOD} rounds={ROUNDS} "
          f"interval={INTERVAL}s telemetry_window={TELEMETRY_WINDOW}s", flush=True)
    while True:
        start = time.time()
        cycle()
        elapsed = time.time() - start
        sleep_s = max(60, INTERVAL - elapsed)
        print(f"cycle done in {elapsed:.0f}s; sleeping {sleep_s:.0f}s", flush=True)
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
