"""Build the cost map from logged telemetry: real spread and activity by hour.

Output: median spread (pips) and tick volume by (symbol x hour-of-week, SAST), a
cheapest-hours ranking, and a CSV. This is the empirical input to the Phase 1b session
filter and the backtest cost model — proprietary, broker-specific, and unavailable
anywhere else.

Run:  python -m telemetry.costmap                       # reads TELEMETRY_DB
      python -m telemetry.costmap --parquet <file>      # from a snapshot
      python -m telemetry.costmap --out data/cost_map.csv
"""
from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from config import settings

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def aggregate(ticks: pd.DataFrame) -> pd.DataFrame:
    """(symbol, hour_of_week) -> median spread pips, tick count. Pure; unit-tested."""
    g = ticks.groupby(["symbol", "hour_of_week"])
    out = g.agg(
        median_spread_pips=("spread_pips", "median"),
        mean_spread_pips=("spread_pips", "mean"),
        tick_count=("spread_pips", "size"),
    ).reset_index()
    out["dow_sast"] = out["hour_of_week"] // 24
    out["hour_sast"] = out["hour_of_week"] % 24
    out["dow"] = out["dow_sast"].map(lambda d: DOW_NAMES[int(d)])
    return out.sort_values(["symbol", "hour_of_week"]).reset_index(drop=True)


def _load(db: str, parquet: str | None) -> pd.DataFrame:
    if parquet:
        return pd.read_parquet(parquet)
    conn = sqlite3.connect(db)
    try:
        return pd.read_sql_query("SELECT * FROM ticks", conn)
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Build the execution cost map from telemetry.")
    p.add_argument("--db", default=settings.TELEMETRY_DB)
    p.add_argument("--parquet", default=None)
    p.add_argument("--out", default="data/cost_map.csv")
    p.add_argument("--min-ticks", type=int, default=5,
                   help="ignore (symbol,hour) buckets thinner than this in the ranking")
    args = p.parse_args()

    ticks = _load(args.db, args.parquet)
    if ticks.empty:
        print("no ticks found. Run the logger first.")
        return
    cm = aggregate(ticks)
    cm.to_csv(args.out, index=False)
    print(f"cost map: {len(cm)} (symbol,hour) buckets -> {args.out}\n")

    ranked = cm[cm["tick_count"] >= args.min_ticks].sort_values("median_spread_pips")
    print(f"cheapest (symbol, hour SAST) to trade — median spread in pips "
          f"(buckets with >= {args.min_ticks} ticks):")
    for _, r in ranked.head(15).iterrows():
        print(f"  {r['symbol']:<8} {r['dow']} {int(r['hour_sast']):02d}:00 SAST   "
              f"{r['median_spread_pips']:.2f} pips   ({int(r['tick_count'])} ticks)")

    print("\nper-symbol cheapest hour observed:")
    for sym, grp in ranked.groupby("symbol"):
        best = grp.iloc[0]
        print(f"  {sym:<8} {best['dow']} {int(best['hour_sast']):02d}:00 SAST   "
              f"{best['median_spread_pips']:.2f} pips")


if __name__ == "__main__":
    main()
