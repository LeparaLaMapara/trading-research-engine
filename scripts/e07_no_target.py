"""Score E07 (docs/programme/E07-let-winners-run-prereg.md): E05 without a profit target.

    python -m scripts.e07_no_target
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from lab import eth_trend as E
from scripts.e05_eth_trend import END, SYMBOL, ann_sharpe

OUT = "docs/results/E07-no-target.json"
N_NULL, N_TRIALS, COST_RT, E05_SHARPE = 200, 300, 11.94e-4, 0.58


def load() -> pd.DataFrame:
    import sqlite3
    with sqlite3.connect("data/market.db") as c:
        return pd.read_sql_query(
            "SELECT ts_utc, open, high, low, close FROM bars WHERE symbol=? AND period='D1' "
            "AND ts_utc < ? ORDER BY ts_utc", c,
            params=(SYMBOL, pd.Timestamp(END, tz="UTC").timestamp()))


def main() -> int:
    bars = load()
    sim = E.simulate(bars, COST_RT, reward_ratio=None)
    r = sim["ret"]
    sr = ann_sharpe(r)
    gross = ann_sharpe(E.simulate(bars, 0.0, reward_ratio=None)["ret"])
    double = ann_sharpe(E.simulate(bars, 2 * COST_RT, reward_ratio=None)["ret"])
    nulls = []
    for seed in range(N_NULL):
        rng = np.random.default_rng(seed)
        signs = pd.Series(rng.choice([-1, 1], size=len(bars)))
        nulls.append(ann_sharpe(E.simulate(bars, COST_RT, signs=signs, reward_ratio=None)["ret"]))
    p95 = float(np.percentile(nulls, 95))
    yearly = r.groupby(r.index.year).sum()
    years = {int(y): float(v) for y, v in yearly.items() if 2018 <= y <= 2025}
    held = sim[sim["pos"] != 0]
    per_trade = held.groupby("trade")["ret"].sum()
    crit = {
        "C1_net_sharpe_positive": sr > 0,
        "C2_beats_null_p95": sr > p95,
        "C3_5_of_8_years_positive": sum(v > 0 for v in years.values()) >= 5,
        "C4_survives_double_costs": double > 0,
        "C5_beats_E05": sr > E05_SHARPE,
    }
    dsr = deflated_sharpe_ratio(r, N_TRIALS, 1.0 / np.sqrt(len(r)))
    res = {
        "experiment": "E07", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample": [str(sim.index[0].date()), str(sim.index[-1].date())], "days": int(len(r)),
        "net_sharpe": round(sr, 3), "e05_net_sharpe": E05_SHARPE,
        "gross_sharpe": round(gross, 3), "null_p95": round(p95, 3),
        "null_mean": round(float(np.mean(nulls)), 3),
        "net_sharpe_double_costs": round(double, 3),
        "net_by_year": {k: round(v, 4) for k, v in years.items()},
        "round_trips": int(sim["trips"].sum()),
        "average_holding_days": round(len(held) / max(1, held["trade"].nunique()), 1),
        "largest_trade_return": round(float(per_trade.max()), 4),
        f"deflated_sharpe_at_N{N_TRIALS}": round(dsr, 3),
        "criteria": crit, "verdict": "PASS" if all(crit.values()) else "FAIL",
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    from research.registry import FailureRegistry
    reg = FailureRegistry()
    tid = reg.record_trial("eth_trend_20d_no_target", {"lookback": 20, "stop_sigmas": 2},
                           SYMBOL, "D1", stage="programme_E07",
                           per_obs_sharpe=float(r.mean() / r.std()), n_bars=int(len(r)))
    reg.set_trial_dsr(tid, dsr)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
