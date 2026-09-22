"""Score E05 Part A: the Ethereum 20-day trend rule on 2017 to 2026 daily history.

    python -m scripts.e05_eth_trend

Writes docs/results/E05-eth-trend.json and records one trial.
"""
from __future__ import annotations

import json
import sqlite3
import time

import numpy as np
import pandas as pd

from backtest.run import measured_cost
from backtest.walkforward import deflated_sharpe_ratio
from lab import eth_trend as E

OUT = "docs/results/E05-eth-trend.json"
SYMBOL, N_NULL, N_TRIALS = "ETHUSD", 200, 298
END = "2026-09-19"                       # bars stored when the pre-registration was written
COMMISSION_SIDE = 0.000035


def ann_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0


def main() -> int:
    with sqlite3.connect("data/market.db") as c:
        bars = pd.read_sql_query(
            "SELECT ts_utc, open, high, low, close FROM bars WHERE symbol=? AND period='D1' "
            "AND ts_utc < ? ORDER BY ts_utc", c,
            params=(SYMBOL, pd.Timestamp(END, tz="UTC").timestamp()))
    ref = float(bars["close"].iloc[-1])
    cm = measured_cost(SYMBOL, ref_price=ref)
    # The spread is a fixed dollar amount now, but ETH traded from under $100 to over $4,000,
    # so it is carried as a FRACTION of price (today's spread over today's price).
    cost_rt = cm.spread_pips * cm.pip_size / ref + 2 * COMMISSION_SIDE

    sim = E.simulate(bars, cost_rt)
    r = sim["ret"]
    sr = ann_sharpe(r)
    gross = ann_sharpe(E.simulate(bars, 0.0)["ret"])
    double = ann_sharpe(E.simulate(bars, 2 * cost_rt)["ret"])

    nulls = []
    for seed in range(N_NULL):
        rng = np.random.default_rng(seed)
        signs = pd.Series(rng.choice([-1, 1], size=len(bars)))
        nulls.append(ann_sharpe(E.simulate(bars, cost_rt, signs=signs)["ret"]))
    p95 = float(np.percentile(nulls, 95))

    yearly = r.groupby(r.index.year).sum()
    years = {int(y): float(v) for y, v in yearly.items() if 2018 <= y <= 2025}
    crit = {
        "C1_net_sharpe_positive": sr > 0,
        "C2_beats_null_p95": sr > p95,
        "C3_5_of_8_years_positive": sum(v > 0 for v in years.values()) >= 5,
        "C4_survives_double_costs": double > 0,
    }
    trips = int(sim["trips"].sum())
    dsr = deflated_sharpe_ratio(r, N_TRIALS, 1.0 / np.sqrt(len(r)))
    res = {
        "experiment": "E05", "part": "A (history)",
        "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample": [str(sim.index[0].date()), str(sim.index[-1].date())], "days": int(len(r)),
        "cost_round_trip_bps": round(cost_rt * 1e4, 2),
        "net_sharpe": round(sr, 3), "gross_sharpe": round(gross, 3),
        "null_p95": round(p95, 3), "null_mean": round(float(np.mean(nulls)), 3),
        "net_sharpe_double_costs": round(double, 3),
        "net_by_year": {k: round(v, 4) for k, v in years.items()},
        "round_trips": trips, "share_of_days_long": round(float((sim["pos"] > 0).mean()), 3),
        "share_of_days_short": round(float((sim["pos"] < 0).mean()), 3),
        "total_return_simple_sum": round(float(r.sum()), 3),
        f"deflated_sharpe_at_N{N_TRIALS}": round(dsr, 3),
        "criteria": crit, "verdict": "PASS" if all(crit.values()) else "FAIL",
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    from research.registry import FailureRegistry
    reg = FailureRegistry()
    tid = reg.record_trial("eth_trend_20d", {"lookback": 20, "stop_sigmas": 2, "rr": 1.5},
                           SYMBOL, "D1", stage="programme_E05",
                           per_obs_sharpe=float(r.mean() / r.std()), n_bars=int(len(r)))
    reg.set_trial_dsr(tid, dsr)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
