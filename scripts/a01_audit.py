"""Run audit A01 (docs/programme/A01-live-rules-audit-prereg.md): the two live rules under
stronger tests. Heavy (20,000 simulations), so it is meant for Databricks:

    gh workflow run databricks-run.yml -f module=scripts.a01_audit

Writes docs/results/A01-live-rules-audit.json. Records no trials: an audit tests nothing new.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from lab import eth_trend as E

OUT = "docs/results/A01-live-rules-audit.json"
N_NULL, N_BOOT, MEAN_BLOCK, N_NOW = 10_000, 10_000, 20, 306
if os.environ.get("A01_QUICK"):          # a smoke run: checks the code, decides nothing
    N_NULL, N_BOOT = 40, 200
    OUT = "docs/results/A01-quick-smoke.json"


def _load(symbol: str, end: str) -> pd.DataFrame:
    with sqlite3.connect("data/market.db") as c:
        return pd.read_sql_query(
            "SELECT ts_utc, open, high, low, close FROM bars WHERE symbol=? AND period='D1' "
            "AND ts_utc < ? ORDER BY ts_utc", c,
            params=(symbol, pd.Timestamp(end, tz="UTC").timestamp()))


def rules() -> dict:
    """Exactly the runs E07 and E08 made: same data window, cost, financing, bars a year."""
    from scripts.e05_eth_trend import END as ETH_END
    e08 = json.load(open("docs/results/E08-fx-trend.json", encoding="utf-8"))["pairs"]["USDSGD"]
    return {
        "E07": {"symbol": "ETHUSD", "end": ETH_END, "cost": 11.94e-4, "bpy": 365.0,
                "kw": {"reward_ratio": None}, "recorded": 0.801},
        "E08-USDSGD": {"symbol": "USDSGD", "end": "2026-09-19",
                       "cost": e08["cost_round_trip_bps"] * 1e-4, "bpy": 260.0,
                       "kw": {"reward_ratio": None, "bars_per_year": 260.0,
                              "long_financing": e08["fee_annual"],
                              "short_financing": e08["fee_annual"]},
                       "recorded": e08["net_sharpe"]},
    }


def ann(r: pd.Series | np.ndarray, bpy: float) -> float:
    r = np.asarray(pd.Series(r).dropna(), dtype=float)
    return float(r.mean() / r.std() * np.sqrt(bpy)) if len(r) > 2 and r.std() > 0 else 0.0


_BARS = None
_SPEC = None


def _init(bars, spec):
    global _BARS, _SPEC
    _BARS, _SPEC = bars, spec


def _null_one(seed: int) -> float:
    rng = np.random.default_rng(seed)
    signs = pd.Series(rng.choice([-1, 1], size=len(_BARS)))
    sim = E.simulate(_BARS, _SPEC["cost"], signs=signs, **_SPEC["kw"])
    return ann(sim["ret"], _SPEC["bpy"])


def stationary_bootstrap(r: np.ndarray, n_boot: int, mean_block: int, bpy: float,
                         seed: int = 0) -> np.ndarray:
    """Politis-Romano stationary bootstrap of the annualised Sharpe. Blocks start at random
    days and have geometric lengths with mean `mean_block`; the series wraps around."""
    rng = np.random.default_rng(seed)
    n, p = len(r), 1.0 / mean_block
    pos = np.arange(n)
    out = np.empty(n_boot)
    for b in range(n_boot):
        jump = rng.random(n) < p
        jump[0] = True                                   # the first day starts a block
        starts = rng.integers(n, size=n)
        seg = np.maximum.accumulate(np.where(jump, pos, 0))   # where the current block began
        idx = (starts[seg] + pos - seg) % n
        s = r[idx]
        out[b] = s.mean() / s.std() * np.sqrt(bpy) if s.std() > 0 else 0.0
    return out


def audit(name: str, spec: dict) -> dict:
    bars = _load(spec["symbol"], spec["end"])
    sim = E.simulate(bars, spec["cost"], **spec["kw"])
    r = sim["ret"].dropna()
    sr = ann(r, spec["bpy"])
    t0 = time.time()
    # Workers are looked up by module name: under `python -m` or Databricks' exec() this file
    # is __main__, which a worker process cannot import, so name the real module.
    from scripts import a01_audit as M
    with ProcessPoolExecutor(max_workers=os.cpu_count(), initializer=M._init,
                             initargs=(bars, spec)) as ex:
        nulls = np.array(list(ex.map(M._null_one, range(N_NULL), chunksize=250)))
    p99 = float(np.percentile(nulls, 99))
    boot = stationary_bootstrap(r.to_numpy(), N_BOOT, MEAN_BLOCK, spec["bpy"])
    share_le0 = float((boot <= 0).mean())
    mid = r.index[len(r) // 2]
    first, second = ann(r[r.index < mid], spec["bpy"]), ann(r[r.index >= mid], spec["bpy"])
    crit = {"K1_beats_10000_null_p99": sr > p99,
            "K2_bootstrap_share_at_or_below_zero_under_10pct": share_le0 < 0.10,
            "K3_both_halves_positive": first > 0 and second > 0}
    out = {
        "symbol": spec["symbol"], "sample": [str(r.index[0].date()), str(r.index[-1].date())],
        "days": int(len(r)), "cost_round_trip_bps": round(spec["cost"] * 1e4, 2),
        "net_sharpe": round(sr, 3), "recorded_net_sharpe": spec["recorded"],
        "reproduces_recorded": abs(round(sr, 3) - spec["recorded"]) < 0.002,
        "null_draws": N_NULL, "null_p99": round(p99, 3), "null_mean": round(float(nulls.mean()), 3),
        "bootstrap_resamples": N_BOOT, "bootstrap_mean_block_days": MEAN_BLOCK,
        "bootstrap_share_at_or_below_zero": round(share_le0, 4),
        "bootstrap_90pct_interval": [round(float(np.percentile(boot, 5)), 3),
                                     round(float(np.percentile(boot, 95)), 3)],
        "net_sharpe_first_half": round(first, 3), "net_sharpe_second_half": round(second, 3),
        "split_day": str(mid.date()),
        f"deflated_sharpe_at_N{N_NOW}": round(deflated_sharpe_ratio(r, N_NOW,
                                                                   1.0 / np.sqrt(len(r))), 3),
        "seconds": round(time.time() - t0),
        "criteria": crit, "verdict": "PASS" if all(crit.values()) else "FAIL",
    }
    if spec["symbol"] == "USDSGD":
        try:
            from backtest.run import measured_cost
            cm = measured_cost("USDSGD", ref_price=float(bars["close"].iloc[-1]))
            c = cm.spread_pips * cm.pip_size / float(bars["close"].iloc[-1]) + 2 * 0.000035
            out["measured_cost_bps_reported_only"] = round(c * 1e4, 2)
            out["net_sharpe_at_measured_cost_reported_only"] = round(
                ann(E.simulate(bars, c, **spec["kw"])["ret"], spec["bpy"]), 3)
            out["measured_cost_source"] = getattr(cm, "source", "")
        except Exception as exc:  # noqa: BLE001 - reported only; never decides
            out["measured_cost_note"] = f"not computed: {exc}"
    return out


def main() -> int:
    per = {name: audit(name, spec) for name, spec in rules().items()}
    res = {"audit": "A01", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "rules": per, "demoted": [k for k, v in per.items() if v["verdict"] == "FAIL"]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=bool)
    print(json.dumps(res, indent=1, default=bool))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
