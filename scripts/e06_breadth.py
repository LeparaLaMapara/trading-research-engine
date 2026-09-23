"""Score E06 (docs/programme/E06-crypto-breadth-prereg.md): E05's rule on eight coins, combined.

    python -m scripts.e06_breadth
"""
from __future__ import annotations

import json
import sqlite3
import time

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from lab import eth_trend as E

OUT = "docs/results/E06-crypto-breadth.json"
COINS = ["ADAUSD", "BCHUSD", "BTCUSD", "DOTUSD", "ETHUSD", "LTCUSD", "SOLUSD", "XRPUSD"]
START, END = "2018-01-01", "2026-09-19"
N_NULL, N_TRIALS, VOL_DAYS = 200, 299, 60
COMMISSION_SIDE, CLASS_DEFAULT_BPS = 0.000035, 15.0


def load(sym: str) -> pd.DataFrame:
    with sqlite3.connect("data/market.db") as c:
        return pd.read_sql_query(
            "SELECT ts_utc, open, high, low, close FROM bars WHERE symbol=? AND period='D1' "
            "AND ts_utc < ? ORDER BY ts_utc", c,
            params=(sym, pd.Timestamp(END, tz="UTC").timestamp()))


def cost_rt(sym: str, ref: float) -> tuple[float, str]:
    summ = json.load(open("data/spread_summary.json", encoding="utf-8")).get(sym)
    if summ and summ.get("pip_position") is not None:
        spread = summ["spread_pips"] * 10 ** (-summ["pip_position"]) / ref
        return spread + 2 * COMMISSION_SIDE, "measured"
    return CLASS_DEFAULT_BPS * 1e-4 + 2 * COMMISSION_SIDE, "class default 15 bps"


def weights(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Inverse 60-day price volatility, from PRIOR days only."""
    cols = {}
    for s, b in bars.items():
        px = pd.Series(b["close"].to_numpy(),
                       index=pd.to_datetime(b["ts_utc"], unit="s", utc=True))
        vol = np.log(px).diff().rolling(VOL_DAYS, min_periods=VOL_DAYS).std().shift(1)
        cols[s] = 1.0 / vol
    return pd.DataFrame(cols)


def combine(rets: dict[str, pd.Series], w: pd.DataFrame) -> pd.Series:
    r = pd.DataFrame(rets)
    w = w.reindex(r.index)[r.columns].where(r.notna())
    w = w.div(w.sum(axis=1), axis=0)
    out = (r * w).sum(axis=1, min_count=1)
    return out[(out.index >= pd.Timestamp(START, tz="UTC"))].dropna()


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0


def main() -> int:
    bars = {s: load(s) for s in COINS}
    bars = {s: b for s, b in bars.items() if len(b) > VOL_DAYS + E.LOOKBACK + 5}
    costs = {s: cost_rt(s, float(b["close"].iloc[-1])) for s, b in bars.items()}
    w = weights(bars)

    def run(mult: float = 1.0, seed: int | None = None) -> dict[str, pd.Series]:
        out = {}
        rng = np.random.default_rng(seed) if seed is not None else None
        for s, b in bars.items():
            signs = (pd.Series(rng.choice([-1, 1], size=len(b))) if rng is not None else None)
            out[s] = E.simulate(b, costs[s][0] * mult, signs=signs)["ret"]
        return out

    per = run()
    port = combine(per, w)
    sr = sharpe(port)
    eth = per["ETHUSD"].reindex(port.index)
    sr_eth = sharpe(eth)
    double = sharpe(combine(run(2.0), w))
    nulls = [sharpe(combine(run(seed=k), w)) for k in range(N_NULL)]
    p95 = float(np.percentile(nulls, 95))
    yearly = port.groupby(port.index.year).sum()
    years = {int(y): float(v) for y, v in yearly.items() if 2018 <= y <= 2025}

    # How many independent bets are really here? From the rule returns' correlations.
    R = pd.DataFrame(per).reindex(port.index)
    corr = R.corr(min_periods=250)
    off = corr.where(~np.eye(len(corr), dtype=bool)).stack()
    lam = np.clip(np.linalg.eigvalsh(corr.fillna(0).to_numpy()), 0, None)
    n_eff = float(lam.sum() ** 2 / (lam ** 2).sum())

    crit = {
        "C1_beats_null_p95": sr > p95,
        "C2_breadth_beats_ethereum_alone": sr > sr_eth,
        "C3_6_of_8_years_positive": sum(v > 0 for v in years.values()) >= 6,
        "C4_survives_double_costs": double > 0,
    }
    dsr = deflated_sharpe_ratio(port, N_TRIALS, 1.0 / np.sqrt(len(port)))
    res = {
        "experiment": "E06", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample": [str(port.index[0].date()), str(port.index[-1].date())],
        "days": int(len(port)), "coins": sorted(bars),
        "net_sharpe_combined": round(sr, 3), "net_sharpe_ethereum_alone": round(sr_eth, 3),
        "null_p95": round(p95, 3), "null_mean": round(float(np.mean(nulls)), 3),
        "net_sharpe_double_costs": round(double, 3),
        "net_by_year": {k: round(v, 4) for k, v in years.items()},
        "net_sharpe_by_coin": {s: round(sharpe(r.reindex(port.index)), 3)
                               for s, r in per.items()},
        "cost_by_coin": {s: {"round_trip_bps": round(c * 1e4, 2), "source": src}
                         for s, (c, src) in costs.items()},
        "mean_pairwise_correlation": round(float(off.mean()), 3),
        "effective_independent_bets": round(n_eff, 2),
        f"deflated_sharpe_at_N{N_TRIALS}": round(dsr, 3),
        "criteria": crit, "verdict": "PASS" if all(crit.values()) else "FAIL",
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    from research.registry import FailureRegistry
    reg = FailureRegistry()
    tid = reg.record_trial("crypto_trend_breadth", {"coins": sorted(bars), "vol_days": VOL_DAYS},
                           "PORTFOLIO", "D1", stage="programme_E06",
                           per_obs_sharpe=float(port.mean() / port.std()), n_bars=int(len(port)))
    reg.set_trial_dsr(tid, dsr)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
