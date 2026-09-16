"""Render background-worker entrypoint: run the research engine on a schedule.

Each cycle: fetch fresh bars, optionally log a bounded telemetry window, then run the
Claude+Gemini council + backtest experiment for every symbol. All data lives on the mounted
persistent disk (the repo's data/ dir), so the Failure Registry and the agent-calibration
scoreboard ACCUMULATE across cycles instead of resetting.

Each reactor-based step (bars, telemetry) runs as a SUBPROCESS because Twisted's reactor is
not restartable within a single long-lived process. This script imports no engine packages;
it only shells out to `python -m <module>`.

Config via env vars (all optional):
  RESEARCH_SYMBOLS   comma list (default: the whole 24-instrument universe)
  RESEARCH_PERIOD    default D1
  RESEARCH_ROUNDS    default 6
  RESEARCH_INTERVAL_S seconds between cycles (default 86400 = daily)
  BARS_YEARS         history depth to fetch (default 12)
  TELEMETRY_WINDOW_S bounded telemetry logging per cycle (default 0 = skip)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

# The universe, not three hand-picked FX pairs. The old default (EURUSD, USDJPY, XAUUSD)
# predates the 24-instrument research universe and was researching a tenth of what the
# engine holds, all of it dollar-correlated.
from config.instruments import universe as _universe

SYMBOLS = [s.strip().upper() for s in os.environ["RESEARCH_SYMBOLS"].split(",") if s.strip()]     if os.environ.get("RESEARCH_SYMBOLS") else _universe()

# D1, not H1. Measured on EURUSD with real tick telemetry, the SAME trend rule costs 0.232
# Sharpe units a year at H1 and 0.010 at D1: over twenty times cheaper for the same idea.
# At H1 every strategy in the registry is above Carver's 0.13 affordability ceiling, so the
# engine was spending its whole search on rules that arithmetic had already ruled out.
PERIOD = os.environ.get("RESEARCH_PERIOD", "D1")
ROUNDS = os.environ.get("RESEARCH_ROUNDS", "6")
INTERVAL = int(os.environ.get("RESEARCH_INTERVAL_S", "86400"))
# 180 days is 180 D1 bars, far too few to fit anything. Years, not days.
BARS_YEARS = os.environ.get("BARS_YEARS", "12")
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
        run(["market.bars", "--symbol", sym, "--period", PERIOD, "--years", BARS_YEARS], 300)
    if TELEMETRY_WINDOW > 0:
        run(["telemetry.logger", "--duration", str(TELEMETRY_WINDOW)], TELEMETRY_WINDOW + 90)
    # Deterministic sweep BEFORE the council. It costs no tokens, it is resumable, and it
    # tells the council which (instrument, model) pairs are even affordable to run.
    run(["scripts.sweep_universe", "--period", PERIOD], 5400)
    for sym in SYMBOLS:
        run(["research.experiment", "--symbol", sym, "--period", PERIOD, "--rounds", ROUNDS], 1800)
    run(["ops.audit"], 300)


def main() -> None:
    print(f"scheduler up. {len(SYMBOLS)} symbols period={PERIOD} rounds={ROUNDS} "
          f"interval={INTERVAL}s telemetry_window={TELEMETRY_WINDOW}s", flush=True)
    print(f"  {', '.join(SYMBOLS)}", flush=True)
    while True:
        start = time.time()
        cycle()
        elapsed = time.time() - start
        sleep_s = max(60, INTERVAL - elapsed)
        print(f"cycle done in {elapsed:.0f}s; sleeping {sleep_s:.0f}s", flush=True)
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
