"""Score E03 (docs/programme/E03-book-imbalance-prereg.md, as amended) on XRPUSD depth.

    python -m scripts.e03_book                  # score, once 120 hours are recorded
    python -m scripts.e03_book --check DB       # diagnostics only, NO returns (for the
                                                # excluded 1.5 hours in data/telemetry.db)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from lab import book as B
from scripts.record_e03 import E03_DB, TARGET_HOURS, hours_recorded

OUT = "docs/results/E03-book-imbalance.json"
SYMBOL, DELAY, HOLD, THRESHOLD = "XRPUSD", 2, 60, 0.6


def load(db: str) -> pd.DataFrame:
    with sqlite3.connect(db) as c:
        return pd.read_sql_query(
            "SELECT ts_utc, quote_id, side, price, size, event FROM depth_quotes "
            "WHERE symbol=? ORDER BY id", c, params=(SYMBOL,))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="DB")
    a = ap.parse_args()

    if a.check:
        df = B.per_second(load(a.check))
        tr = B.trades(df, THRESHOLD, DELAY, HOLD)
        print(f"seconds rebuilt {len(df)}, |I| >= {THRESHOLD} in "
              f"{(df['I'].abs() >= THRESHOLD).mean():.3f} of them, trades the rule would "
              f"take {len(tr)}. (Returns deliberately not computed.)")
        return 0

    h = hours_recorded()
    if h < TARGET_HOURS:
        print(f"not scoring: {h:.1f} of {TARGET_HOURS:.0f} hours recorded")
        return 1
    df = B.per_second(load(E03_DB))
    fwd = (B.future(df, "mid", DELAY + HOLD) - B.future(df, "mid", DELAY)) / df["mid"]
    ok = fwd.notna()
    rho, p = spearmanr(df.loc[ok, "I"], fwd[ok])
    # As pre-registered, C1 uses every second. Overlapping 60 s windows make that p value
    # too small, so a non-overlapping version (one sample per 62 s) is reported beside it.
    step = df.loc[ok].iloc[::DELAY + HOLD]
    rho_n, p_n = spearmanr(step["I"], fwd[step.index])

    tr = B.trades(df, THRESHOLD, DELAY, HOLD)
    n = len(tr)
    mean = float(tr["net"].mean()) if n else float("nan")
    t_stat = float(mean / (tr["net"].std(ddof=1) / np.sqrt(n))) if n > 1 else float("nan")
    mid_t = df.index.min() + (df.index.max() - df.index.min()) / 2
    halves = [float(tr.loc[tr["t"] < mid_t, "net"].mean()),
              float(tr.loc[tr["t"] >= mid_t, "net"].mean())]
    crit = {
        "C1_rank_correlation_positive_p_lt_0.01": bool(rho > 0 and p < 0.01),
        "C2_mean_net_positive_t_gt_2": bool(n > 1 and mean > 0 and t_stat > 2),
        "C3_positive_in_both_halves": bool(all(np.isfinite(x) and x > 0 for x in halves)),
    }
    res = {
        "experiment": "E03", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "symbol": SYMBOL, "hours_recorded": round(h, 1), "seconds": int(len(df)),
        "rank_correlation": round(float(rho), 4), "p_value": float(p),
        "rank_correlation_non_overlapping": round(float(rho_n), 4),
        "p_value_non_overlapping": float(p_n),
        "trades": n, "mean_net_per_trade": mean, "t_stat": t_stat,
        "mean_net_by_half": halves,
        "criteria": crit, "verdict": "PASS" if all(crit.values()) else "FAIL",
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
