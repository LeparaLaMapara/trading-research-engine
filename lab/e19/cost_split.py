"""E19 scoping: split the 2026-09-19 long-history trend result into spread vs financing.

Pre-holdout data only (same loader and mask as scripts/long_history.py). Counted as trials in
E19: tsmom_12m (2026-11-19 run 1), and ewmac, breakout, blend (run 2). Splits by asset class
and era are slices of the same trials, not new ones.

Bug fixed 2026-11-19 (run 2): the panel drops warm-up rows, so no row is before 2004 and the
training mask `tr` is empty. ewmac normalised each speed by a mean over zero rows (NaN), and
scaled() then turned the whole forecast into zeros. Now, exactly as scripts/long_history.py
does, the scale falls back to all rows when `tr` is empty. The scale is one positive constant
per speed: it cannot change a sign, only the speed weights and how often the +/-2 cap binds.

Run: PYTHONPATH=. python lab/e19/cost_split.py
"""
import json
import os

import numpy as np
import pandas as pd

os.environ.setdefault("ARTIFACT_ROOT", "/mnt/t/making-money")
from scripts import long_history as L
from scripts.train_zoo import scaled, sharpe
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

OUT = "docs/results/e19-cost-split-2026-11-19.json"

paths = L.files()
p = build_panel(sorted(paths), loader=L.loader_for(paths))
for s, c in L.EXTRA_CLASS.items():
    p.loc[p.symbol == s, "asset_class"] = c
costs = cost_table(p)
for s, (c, fin) in L.EXTRA_COST.items():
    if s in costs.index:
        costs.loc[s, ["cost", "fin"]] = [c, fin / 260.0]

tr = p.date < pd.Timestamp("2004-01-01")
allr = pd.Series(True, index=p.index)
fit = tr if tr.any() else allr                       # the fix (mirrors long_history.py)
whole = (p.date >= pd.Timestamp("2004-01-01")) & (p.date < L.HOLDOUT_START)
cls = p.groupby("symbol").asset_class.first()
print(f"panel {p.symbol.nunique()} instruments, {len(p):,} rows, "
      f"{p.date.min().date()} to {p.date.max().date()}; pre-2004 rows {int(tr.sum())}")
print("classes:", cls.value_counts().to_dict())

fc = {}
for n, fn in (("ewmac", Z.ewmac), ("breakout", Z.breakout), ("tsmom_12m", Z.tsmom_12m)):
    raw = np.asarray(fn(p, fit, allr), float)
    ref = np.ones(1) if n == "tsmom_12m" else np.asarray(fn(p, fit, fit), float)
    fc[n] = pd.Series(scaled(raw, ref), index=p.index)
    assert fc[n].abs().sum() > 0, f"{n} forecast is all zero"
b = (fc["ewmac"] + fc["breakout"] + fc["tsmom_12m"]) / 3.0
fc["blend"] = (b / b[fit].abs().mean()).clip(-2, 2)

no_fin = costs.assign(fin=0.0)


def stats(d):
    per = {k: round(sharpe(d.net[(d.index >= a) & (d.index < bb)], 260), 2)
           for k, (a, bb) in L.PERIODS.items()}
    return {"gross": round(sharpe(d.gross, 260), 3), "net": round(sharpe(d.net, 260), 3),
            "tcost_over_gross": round(float(d.tcost.sum() / d.gross.sum()), 3)
            if d.gross.sum() > 0 else None,
            "fcost_over_gross": round(float(d.fcost.sum() / d.gross.sum()), 3)
            if d.gross.sum() > 0 else None,
            "annual_turnover": round(float(d.turn.mean() * 260), 1), "periods": per}


res = {"panel": {"instruments": int(p.symbol.nunique()), "rows": int(len(p)),
                 "classes": cls.value_counts().to_dict()}, "rules": {}}
for n, f in fc.items():
    r = {"cfd": stats(portfolio_returns(p, f, costs, whole)),
         "spread_only": stats(portfolio_returns(p, f, no_fin, whole)), "by_class": {}}
    for c in sorted(cls.unique()):
        syms = cls.index[cls == c]
        sub = p.symbol.isin(syms)
        ps = p[sub]
        r["by_class"][c] = {"n": int(len(syms)),
                            **stats(portfolio_returns(ps, f[sub], no_fin, whole[sub]))}
    res["rules"][n] = r
    print(f"\n{n}: cfd gross {r['cfd']['gross']} net {r['cfd']['net']} | spread-only net "
          f"{r['spread_only']['net']} {r['spread_only']['periods']} turnover "
          f"{r['spread_only']['annual_turnover']}/yr")
    for c, s in r["by_class"].items():
        print(f"   {c:<10} n={s['n']:<3} gross {s['gross']:>6} net {s['net']:>6} {s['periods']}")

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(res, fh, indent=1, default=float)
print("\nwrote", OUT)
