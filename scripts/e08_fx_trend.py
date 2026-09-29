"""Score E08 (docs/programme/E08-fx-trend-affordable-prereg.md): the live trend rule (E07) on
the five currency pairs the account can afford.

    python -m scripts.e08_fx_trend

Writes docs/results/E08-fx-trend.json and records one trial per pair.
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
from zoo import financing as F

OUT = "docs/results/E08-fx-trend.json"
PAIRS = ("AUDCAD", "AUDNZD", "EURCAD", "EURGBP", "USDSGD")
END = "2026-09-19"
N_NULL, N_TRIALS, BARS_PER_YEAR = 200, 305, 260.0
COMMISSION_SIDE = 0.000035
YEARS = range(2015, 2026)


def ann_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * np.sqrt(BARS_PER_YEAR)) if len(r) > 2 and r.std() > 0 else 0.0


def load(symbol: str) -> pd.DataFrame:
    with sqlite3.connect("data/market.db") as c:
        return pd.read_sql_query(
            "SELECT ts_utc, open, high, low, close FROM bars WHERE symbol=? AND period='D1' "
            "AND ts_utc < ? ORDER BY ts_utc", c,
            params=(symbol, pd.Timestamp(END, tz="UTC").timestamp()))


def score(symbol: str, swaps: dict) -> dict:
    bars = load(symbol)
    ref = float(bars["close"].iloc[-1])
    cm = measured_cost(symbol, ref_price=ref)
    cost_rt = cm.spread_pips * cm.pip_size / ref + 2 * COMMISSION_SIDE
    fee, _diff = F.fee_and_differential(swaps[symbol], ref)
    # Annual COST (positive = pay). Main run: the broker's fee, both directions (prereg).
    fee_cost = fee
    long_rate, short_rate = F.annual_rates(swaps[symbol], ref)     # negative = you pay
    kw = dict(reward_ratio=None, bars_per_year=BARS_PER_YEAR)

    def run(cost, lf=fee_cost, sf=fee_cost, signs=None):
        return E.simulate(bars, cost, signs=signs, long_financing=lf, short_financing=sf, **kw)

    sim = run(cost_rt)
    r = sim["ret"]
    sr = ann_sharpe(r)
    gross = ann_sharpe(run(0.0, 0.0, 0.0)["ret"])
    double = ann_sharpe(run(2 * cost_rt)["ret"])
    today_swap = ann_sharpe(run(cost_rt, -long_rate, -short_rate)["ret"])
    nulls = []
    for seed in range(N_NULL):
        rng = np.random.default_rng(seed)
        signs = pd.Series(rng.choice([-1, 1], size=len(bars)))
        nulls.append(ann_sharpe(run(cost_rt, signs=signs)["ret"]))
    p99 = float(np.percentile(nulls, 99))
    yearly = r.groupby(r.index.year).sum()
    years = {int(y): float(v) for y, v in yearly.items() if y in YEARS}
    crit = {
        "C1_net_sharpe_positive": sr > 0,
        "C2_beats_null_p99": sr > p99,
        "C3_7_of_11_years_positive": sum(v > 0 for v in years.values()) >= 7,
        "C4_survives_double_costs": double > 0,
        "C5_survives_todays_full_swap": today_swap > 0,
    }
    dsr = deflated_sharpe_ratio(r, N_TRIALS, 1.0 / np.sqrt(len(r)))
    from research.registry import FailureRegistry
    reg = FailureRegistry()
    tid = reg.record_trial("eth_trend_20d_no_target", {"lookback": 20, "stop_sigmas": 2},
                           symbol, "D1", stage="programme_E08",
                           per_obs_sharpe=float(r.mean() / r.std()), n_bars=int(len(r)))
    reg.set_trial_dsr(tid, dsr)
    return {
        "sample": [str(sim.index[0].date()), str(sim.index[-1].date())], "days": int(len(r)),
        "cost_round_trip_bps": round(cost_rt * 1e4, 2), "spread_source": getattr(cm, "source", "see console"),
        "fee_annual": round(fee, 5),
        "todays_swap_annual_long_short": [round(long_rate, 5), round(short_rate, 5)],
        "net_sharpe": round(sr, 3), "gross_sharpe": round(gross, 3),
        "null_p99": round(p99, 3), "null_mean": round(float(np.mean(nulls)), 3),
        "net_sharpe_double_costs": round(double, 3),
        "net_sharpe_todays_full_swap": round(today_swap, 3),
        "net_by_year": {k: round(v, 4) for k, v in years.items()},
        "years_positive": f"{sum(v > 0 for v in years.values())} of {len(years)}",
        "round_trips": int(sim["trips"].sum()),
        f"deflated_sharpe_at_N{N_TRIALS}": round(dsr, 3),
        "criteria": crit, "verdict": "PASS" if all(crit.values()) else "FAIL",
    }


def main() -> int:
    swaps = F.load()
    per = {s: score(s, swaps) for s in PAIRS}
    passed = [s for s, v in per.items() if v["verdict"] == "PASS"]
    res = {"experiment": "E08", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "pairs": per, "passed": passed, "verdict": "PASS" if passed else "FAIL"}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=bool)
    print(json.dumps(res, indent=1, default=bool))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
