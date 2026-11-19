"""E19 scoping: split the 2026-09-19 long-history trend loss into spread vs financing.
Pre-holdout data only (same mask as scripts/long_history.py). Counted as trials in the E19 prereg."""
import os, sys, numpy as np, pandas as pd
os.environ.setdefault("ARTIFACT_ROOT", "/mnt/t/making-money")
from scripts import long_history as L
from scripts.train_zoo import scaled, sharpe
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns
paths = L.files(); p = build_panel(sorted(paths), loader=L.loader_for(paths))
for s, c in L.EXTRA_CLASS.items(): p.loc[p.symbol == s, "asset_class"] = c
costs = cost_table(p)
for s, (c, fin) in L.EXTRA_COST.items():
    if s in costs.index: costs.loc[s, ["cost", "fin"]] = [c, fin / 260.0]
tr = p.date < pd.Timestamp("2004-01-01"); allr = pd.Series(True, index=p.index)
whole = (p.date >= pd.Timestamp("2004-01-01")) & (p.date < L.HOLDOUT_START)
print(costs[["cost","fin"]].assign(fin_annual=costs.fin*260).drop(columns="fin").groupby(p.groupby("symbol").asset_class.first()).median())
for n, fn in (("ewmac", Z.ewmac), ("tsmom_12m", Z.tsmom_12m)):
    raw = np.asarray(fn(p, tr, allr), float)
    ref = np.ones(1) if n == "tsmom_12m" else np.asarray(fn(p, tr, tr), float)
    f = pd.Series(scaled(raw, ref), index=p.index)
    for label, cst in (("cfd", costs), ("no_fin", costs.assign(fin=0.0))):
        d = portfolio_returns(p, f, cst, whole)
        print(n, label, "gross", round(sharpe(d.gross, 260), 3), "net", round(sharpe(d.net, 260), 3),
              {k: round(sharpe(d.net[(d.index >= a) & (d.index < b)], 260), 2) for k, (a, b) in L.PERIODS.items()})
    # by class, no financing
    d = portfolio_returns(p, f, costs.assign(fin=0.0), whole)
