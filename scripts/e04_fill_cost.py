"""Score E04 (docs/programme/E04-fill-cost-prereg.md) from the trade log.

    python -m scripts.e04_fill_cost

Reads probe legs with trade_id above 13, writes docs/results/E04-fill-cost.json.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time

import numpy as np

from backtest.run import _spread_summary

TRADE_LOG = "data/trade_log.db"
OUT = "docs/results/E04-fill-cost.json"
FIRST_ID = 14
PIP, UNITS = 0.0001, 1000.0          # EURUSD, 0.01 lots


def _lat(note: str | None, key: str) -> float | None:
    m = re.search(rf"{key}=(\d+)", note or "")
    return float(m.group(1)) if m else None


def main() -> int:
    c = sqlite3.connect(TRADE_LOG)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM trade_log WHERE trade_id >= ? AND purpose='telemetry_probe' "
        "ORDER BY trade_id", (FIRST_ID,))]
    opens = [r for r in rows if r["status"] == "FILLED"]
    closes = [r for r in rows if r["status"] == "CLOSED"]
    rejected = [r for r in rows if r["status"] == "REJECTED"]

    entry_slip = [r["slippage_pips"] for r in opens if r["slippage_pips"] is not None]
    exit_slip = [r["slippage_pips"] for r in closes if r["slippage_pips"] is not None]
    legs = entry_slip + exit_slip
    net = [-r["net_pnl"] for r in closes if r["net_pnl"] is not None]       # cost, positive
    commission = [abs(r["commission"] or 0) for r in opens + closes]
    comm_rt = 2 * float(np.mean(commission)) if commission else None
    spread_pips = float(_spread_summary().get("EURUSD", {}).get("spread_pips", 0.1))
    modelled = spread_pips * PIP * UNITS + (comm_rt or 0.0)
    open_lat = [x for x in (_lat(r["note"], "open_latency_ms") for r in opens) if x is not None]
    close_lat = [x for x in (_lat(r["note"], "close_latency_ms") for r in closes) if x is not None]

    mean_leg = float(np.mean(legs)) if legs else None
    mean_net = float(np.mean(net)) if net else None
    crit = {
        "C1_mean_adverse_slippage_per_leg_le_0.1_pip":
            mean_leg is not None and mean_leg <= 0.1,
        "C2_mean_net_cost_le_1.25x_modelled":
            mean_net is not None and mean_net <= 1.25 * modelled,
    }
    res = {
        "experiment": "E04", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "measurements": {
            "n_probes": len(closes), "n_rejected": len(rejected),
            "entry_legs_measured": len(entry_slip), "exit_legs_measured": len(exit_slip),
            "mean_adverse_slippage_pips": None if mean_leg is None else round(mean_leg, 4),
            "p95_adverse_slippage_pips": round(float(np.percentile(legs, 95)), 4) if legs else None,
            "max_adverse_slippage_pips": round(float(np.max(legs)), 4) if legs else None,
            "mean_entry_slippage_pips": round(float(np.mean(entry_slip)), 4) if entry_slip else None,
            "mean_exit_slippage_pips": round(float(np.mean(exit_slip)), 4) if exit_slip else None,
            "mean_net_cost_usd": None if mean_net is None else round(mean_net, 4),
            "total_net_cost_usd": round(float(np.sum(net)), 2) if net else None,
            "modelled_cost_usd": round(modelled, 4),
            "commission_round_trip_usd": None if comm_rt is None else round(comm_rt, 4),
            "spread_used_in_model_pips": spread_pips,
            "mean_latency_ms": round(float(np.mean(open_lat + close_lat)), 0)
            if open_lat + close_lat else None,
            "mean_open_latency_ms": round(float(np.mean(open_lat)), 0) if open_lat else None,
            "mean_close_latency_ms": round(float(np.mean(close_lat)), 0) if close_lat else None,
        },
        "criteria": crit,
        "verdict": "PASS" if all(crit.values()) else "FAIL",
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
