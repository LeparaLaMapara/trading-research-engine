"""Slow relative ML, per docs/results/zoo-followup-preregistration-2026-09-19.md.

Run:  python -m scripts.zoo_followup
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from backtest import walkforward as wf
from config.instruments import extended_universe
from scripts.train_zoo import (DB, HOLDOUT_START, ann_factor, block_bootstrap_sharpe,
                               ensemble, honest_n, max_dd, oos_forecast, sharpe)
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

PROGRAMME = "zoo-followup-2026-09-19"
BASES = ("xgb_shallow", "extra_trees", "ens_ml")
SPANS = (10, 30)


def slow_relative(f: pd.Series, p: pd.DataFrame, span: int) -> pd.Series:
    rel = f - f.groupby(p["date"]).transform("mean")
    sm = rel.groupby(p["symbol"]).transform(lambda s: s.ewm(span=span, min_periods=1).mean())
    sm = sm.where(f.notna())
    out = sm.copy()
    yr = p["date"].dt.year.where(p["date"] < HOLDOUT_START, 9999)
    for y in sorted(yr.unique()):
        prior = sm[(yr < y) & sm.notna()]
        k = 1.0 / prior.abs().mean() if len(prior) and prior.abs().mean() > 0 else 1.0
        out[yr == y] = (sm[yr == y] * k).clip(-2, 2)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    p = build_panel(extended_universe())
    costs = cost_table(p)
    fc = {n: oos_forecast(n, p, None) for n in Z.LEARNED}
    fc["ens_ml"] = ensemble(Z.ENSEMBLES["ens_ml"], fc, p)
    dev = (p["date"] >= pd.Timestamp("2017-01-01")) & (p["date"] < HOLDOUT_START)

    rows = []
    for b in BASES:
        for s in SPANS:
            name = f"rel_{b}_s{s}"
            f = slow_relative(fc[b], p, s)
            d = portfolio_returns(p, f, costs, dev)
            af = ann_factor(d)
            yearly = {int(y): round(sharpe(g["net"], af), 3) for y, g in d.groupby(d.index.year)}
            rows.append({"model": name, "dev_sharpe": sharpe(d["net"], af),
                         "gross_sharpe": sharpe(d["gross"], af), "per_obs": wf.per_obs_sharpe(d["net"]),
                         "yearly": yearly, "years_positive": sum(v > 0 for v in yearly.values()),
                         "turnover": float(d["turn"].mean() * af), "max_dd": max_dd(d["net"]),
                         "af": af, "daily": d})
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM trials WHERE variant LIKE ?", (f"{PROGRAMME}:%",))
    now = time.time()
    for r in rows:
        conn.execute("INSERT INTO trials (variant, strategy_kind, symbol, period, stage, "
                     "per_obs_sharpe, n_bars, created_ts) VALUES (?,?,?,?,?,?,?,?)",
                     (f"{PROGRAMME}:{r['model']}", r["model"], "PORTFOLIO64", "D1",
                      "zoo_followup_dev", r["per_obs"], len(r["daily"]), now))
    conn.commit()
    N = honest_n(conn)
    spread = float(np.std([x[0] for x in conn.execute(
        "SELECT per_obs_sharpe FROM trials WHERE stage IN ('zoo_dev','carry_dev','zoo_followup_dev')")]))
    for r in rows:
        r["dsr"] = wf.deflated_sharpe_ratio(r["daily"]["net"], N, spread)
        r["ci"] = block_bootstrap_sharpe(r["daily"]["net"].to_numpy(), r["af"])
    rows.sort(key=lambda r: r["dev_sharpe"], reverse=True)
    print(f"honest N = {N}\n")
    print(f"{'model':<24}{'dev net':>8}{'gross':>8}{'turn/yr':>8}{'yrs+':>6}{'maxDD':>7}{'DSR':>7}   95% CI")
    for r in rows:
        print(f"{r['model']:<24}{r['dev_sharpe']:>8.3f}{r['gross_sharpe']:>8.3f}{r['turnover']:>8.1f}"
              f"{r['years_positive']:>4}/8{r['max_dd']:>7.2f}{r['dsr']:>7.3f}   "
              f"[{r['ci'][0]:.2f}, {r['ci'][1]:.2f}]  {r['yearly']}")
    with open("docs/results/zoo-followup-2026-09-19.json", "w", encoding="utf-8") as fh:
        json.dump({"N": N, "table": [{k: v for k, v in r.items() if k not in ("daily", "af")}
                                     for r in rows]}, fh, indent=1, default=float)
    print(f"({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
