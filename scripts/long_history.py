"""Trend rules over 23 years of Dukascopy daily data.

Protocol: docs/results/long-history-preregistration-2026-09-19.md.
Run:  python -m scripts.long_history
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from backtest import walkforward as wf
from scripts.train_zoo import (DB, HOLDOUT_START, block_bootstrap_sharpe, honest_n, max_dd,
                               scaled, sharpe)
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

DIR = os.path.join(os.environ.get("ARTIFACT_ROOT", r"T:\making-money"), "features", "dukascopy")
PROGRAMME = "long-history-2026-09-19"
#: Dukascopy instrument -> broker-style symbol, so costs and classes come from the same tables.
NAMES = {"usa500idxusd": "US500", "usa30idxusd": "US30", "usatechidxusd": "USTEC",
         "deuidxeur": "DE40", "gbridxgbp": "UK100", "jpnidxjpy": "JP225", "fraidxeur": "F40",
         "ausidxaud": "AUS200", "hkgidxhkd": "HK50", "eusidxeur": "STOXX50",
         "lightcmdusd": "XTIUSD", "gascmdusd": "XNGUSD", "bundtreur": "BUND",
         "ustbondtrusd": "USTBOND", "cocoacmdusd": "COCOA"}
EXTRA_CLASS = {"BUND": "bond", "USTBOND": "bond", "COCOA": "ag"}
EXTRA_COST = {"BUND": (0.00012, 0.01), "USTBOND": (0.00012, 0.01), "COCOA": (0.0006, 0.01)}
PERIODS = {"2004-2008": ("2004-01-01", "2009-01-01"), "2009-2016": ("2009-01-01", "2017-01-01"),
           "2017-2024": ("2017-01-01", str(HOLDOUT_START.date()))}


def files() -> dict[str, str]:
    out = {}
    for f in glob.glob(os.path.join(DIR, "*-d1-bid-*.csv")):
        key = os.path.basename(f).split("-d1-")[0]
        out[NAMES.get(key, key.upper())] = f
    return out


def loader_for(paths: dict[str, str]):
    def load(sym: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(paths[sym])
        except (pd.errors.EmptyDataError, KeyError):
            return pd.DataFrame()
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms").dt.normalize()
        df = df[(df["date"].dt.dayofweek < 5) & (df["high"] > df["low"])]
        df = df[df["date"] < HOLDOUT_START]            # the holdout stays locked
        return df.drop_duplicates("date").set_index("date")[["high", "low", "close"]]
    return load


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    paths = files()
    p = build_panel(sorted(paths), loader=loader_for(paths))
    for s, c in EXTRA_CLASS.items():
        p.loc[p["symbol"] == s, "asset_class"] = c
    costs = cost_table(p)
    for s, (c, fin) in EXTRA_COST.items():
        if s in costs.index:
            costs.loc[s, ["cost", "fin"]] = [c, fin / 260.0]
    print(f"panel: {p['symbol'].nunique()} instruments, {len(p):,} rows, "
          f"{p['date'].min().date()} to {p['date'].max().date()}")

    # Rules have no fitted parameters; only the scale is set, from data BEFORE 2004.
    tr = p["date"] < pd.Timestamp("2004-01-01")
    allrows = pd.Series(True, index=p.index)
    fc = {}
    for n, fn in (("long_risk_parity", Z.long_risk_parity), ("ewmac", Z.ewmac),
                  ("breakout", Z.breakout), ("tsmom_12m", Z.tsmom_12m)):
        raw = np.asarray(fn(p, tr if tr.any() else allrows, allrows), float)
        ref = np.ones(1) if n in ("long_risk_parity", "tsmom_12m") else \
            np.asarray(fn(p, tr if tr.any() else allrows, tr if tr.any() else allrows), float)
        fc[n] = pd.Series(scaled(raw, ref), index=p.index)
    blend = (fc["ewmac"] + fc["breakout"] + fc["tsmom_12m"]) / 3.0
    prior = blend[tr]
    fc["ens_rules3"] = (blend / (prior.abs().mean() if len(prior) else blend.abs().mean())).clip(-2, 2)

    whole = (p["date"] >= pd.Timestamp("2004-01-01")) & (p["date"] < HOLDOUT_START)
    rows = []
    for n, f in fc.items():
        d = portfolio_returns(p, f, costs, whole)
        per = {}
        for k, (a, b) in PERIODS.items():
            g = d[(d.index >= a) & (d.index < b)]
            per[k] = round(sharpe(g["net"], 260), 3)
        yearly = {int(y): round(sharpe(g["net"], 260), 2) for y, g in d.groupby(d.index.year)}
        rows.append({"model": n, "net": sharpe(d["net"], 260), "gross": sharpe(d["gross"], 260),
                     "per_obs": wf.per_obs_sharpe(d["net"]), "periods": per, "yearly": yearly,
                     "years_positive": sum(v > 0 for v in yearly.values()),
                     "max_dd": max_dd(d["net"]), "daily": d,
                     "ci": block_bootstrap_sharpe(d["net"].to_numpy(), 260)})

    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM trials WHERE variant LIKE ?", (f"{PROGRAMME}:%",))
    now = time.time()
    for r in rows:
        conn.execute("INSERT INTO trials (variant, strategy_kind, symbol, period, stage, "
                     "per_obs_sharpe, n_bars, created_ts) VALUES (?,?,?,?,?,?,?,?)",
                     (f"{PROGRAMME}:{r['model']}", r["model"], "DUKA38", "D1", "long_history",
                      r["per_obs"], len(r["daily"]), now))
    conn.commit()
    N = honest_n(conn)
    spread = float(np.std([x[0] for x in conn.execute(
        "SELECT per_obs_sharpe FROM trials WHERE stage IN "
        "('zoo_dev','carry_dev','zoo_followup_dev','long_history')")]))
    for r in rows:
        r["dsr"] = wf.deflated_sharpe_ratio(r["daily"]["net"], N, spread)

    print(f"\nhonest N = {N}\n")
    print(f"{'model':<18}{'net':>7}{'gross':>7}{'2004-08':>9}{'2009-16':>9}{'2017-24':>9}"
          f"{'yrs+':>7}{'maxDD':>7}{'DSR':>7}   95% CI")
    for r in sorted(rows, key=lambda r: -r["net"]):
        pr = r["periods"]
        print(f"{r['model']:<18}{r['net']:>7.3f}{r['gross']:>7.3f}{pr['2004-2008']:>9.3f}"
              f"{pr['2009-2016']:>9.3f}{pr['2017-2024']:>9.3f}{r['years_positive']:>4}/"
              f"{len(r['yearly']):<2}{r['max_dd']:>7.2f}{r['dsr']:>7.3f}   "
              f"[{r['ci'][0]:.2f}, {r['ci'][1]:.2f}]")
    print("\nyearly (ens_rules3):", next(r for r in rows if r["model"] == "ens_rules3")["yearly"])
    with open("docs/results/long-history-2026-09-19.json", "w", encoding="utf-8") as fh:
        json.dump({"N": N, "instruments": sorted(p["symbol"].unique()),
                   "table": [{k: v for k, v in r.items() if k != "daily"} for r in rows]},
                  fh, indent=1, default=float)
    print(f"({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
