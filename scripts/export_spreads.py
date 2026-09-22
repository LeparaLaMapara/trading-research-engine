"""Export the measured spread per symbol to data/spread_summary.json, which IS committed.

The ticks live in data/telemetry.db on the house machine and never reach CI, so until
2026-09-22 the daily research run costed every symbol with the class default while this
machine held tens of thousands of real quotes. This writes the same number measured_cost()
would compute locally, with its source string and the export date, so CI can use it and a
reader can see how stale it is. Re-run after a recording session:

    python -m scripts.export_spreads
"""
from __future__ import annotations

import json
import sqlite3
import time

from backtest.run import _admissible_spreads, spread_from_ticks
from config import settings


def main() -> int:
    out: dict[str, dict] = {}
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with sqlite3.connect(settings.TELEMETRY_DB) as c:
        specs = dict(c.execute("SELECT symbol, pip_position FROM symbol_spec").fetchall())
        symbols = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ticks ORDER BY symbol")]
        for sym in symbols:
            spread, source = spread_from_ticks(_admissible_spreads(c, sym), sym)
            if spread is None:
                continue
            out[sym] = {"spread_pips": round(spread, 4), "pip_position": specs.get(sym),
                        "source": source, "exported": today}
    with open(settings.SPREAD_SUMMARY, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"wrote {len(out)} symbol(s) to {settings.SPREAD_SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
