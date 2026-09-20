"""What this machine's latency actually is, as distributions rather than averages.

Reads what has already been measured (the broker round-trip probes, and market-data receive
latency once the logger has recorded server timestamps), reports min/median/p90/p95/p99/max
plus jitter and outliers, and copies the observations into `latency_events` so every future
measurement lands in one place with attribution.

    python -m scripts.latency_report
"""
from __future__ import annotations

import sqlite3
import sys

import numpy as np

from config import settings
from lab import registry


def dist(vals: list[float]) -> dict:
    a = np.array(vals, dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {}
    return {"n": len(a), "min": a.min(), "median": np.median(a), "p90": np.percentile(a, 90),
            "p95": np.percentile(a, 95), "p99": np.percentile(a, 99), "max": a.max(),
            "jitter_iqr": np.percentile(a, 75) - np.percentile(a, 25),
            "outliers_over_p99": int((a > np.percentile(a, 99)).sum())}


def show(name: str, d: dict) -> None:
    if not d:
        print(f"{name:<28} no samples yet")
        return
    print(f"{name:<28}n={d['n']:>7}  min {d['min']:>8.1f}  med {d['median']:>8.1f}  "
          f"p90 {d['p90']:>8.1f}  p95 {d['p95']:>8.1f}  p99 {d['p99']:>9.1f}  "
          f"max {d['max']:>9.1f}  jitter {d['jitter_iqr']:>7.1f}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    c = sqlite3.connect(settings.TELEMETRY_DB)
    probes = [r[0] for r in c.execute("SELECT rtt_ms FROM latency")]
    # A subscription's FIRST event for each symbol is the last known quote, which on a closed
    # market is hours or days old. Counting that as "latency" would report 36 hours and be
    # nonsense, so anything older than a minute is a stale snapshot, reported separately.
    STALE_MS = 60_000.0
    recv = [r[0] for r in c.execute(
        "SELECT recv_latency_ms FROM ticks WHERE recv_latency_ms IS NOT NULL "
        "AND recv_latency_ms <= ?", (STALE_MS,))]
    stale = c.execute("SELECT count(*) FROM ticks WHERE recv_latency_ms > ?",
                      (STALE_MS,)).fetchone()[0]
    stamped, total = c.execute(
        "SELECT sum(server_ts IS NOT NULL), count(*) FROM ticks WHERE id > "
        "(SELECT max(id) - 500 FROM ticks)").fetchone()
    by_symbol = c.execute(
        "SELECT symbol, count(*), avg(recv_latency_ms) FROM ticks "
        "WHERE recv_latency_ms IS NOT NULL AND recv_latency_ms <= ? "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 8", (STALE_MS,)).fetchall()
    c.close()

    print("\nAll values in milliseconds.\n")
    show("broker round trip (order path)", dist(probes))
    show("market data receive", dist(recv))
    if by_symbol:
        print("\nmarket data receive, by instrument:")
        for sym, n, avg in by_symbol:
            print(f"  {sym:<10}n={n:>7}  mean {avg:>8.1f}")
    else:
        print("\nmarket data receive: nothing recorded yet. Run the tick logger after "
              "2026-09-20; older rows predate server-timestamp capture.")

    for v in probes:
        registry.record_latency("broker_round_trip", v, stage_mode="probe",
                                exchange="ctrader", mode="probe")
    for v in recv:
        registry.record_latency("market_data_receive", v, exchange="ctrader", mode="stream")
    print(f"\ncopied {len(probes) + len(recv)} observations into latency_events")

    p = registry.percentiles("broker_round_trip")
    if p:
        print(f"\nThe number that decides what we can trade: a typical order leaves and is "
              f"acknowledged in {p['median']:.0f}ms, and one in a hundred takes over "
              f"{p['p99']:.0f}ms. Any edge that dies inside that window is out of reach from "
              f"this house, whatever the backtest says.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
