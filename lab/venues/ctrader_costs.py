"""cTrader CFD cost table for VENUES.md: measured spread and measured financing per symbol.

Uses the same cost model the backtests use (zoo.portfolio.cost_table: measured median spread
from data/spread_summary.json plus commission, and measured swap rates from data/swaps.json),
over the same 39-market Dukascopy daily panel as lab/e19/cost_split.py. Prints costs only, no
strategy performance, so it spends no trials.

Run: PYTHONPATH=. ARTIFACT_ROOT=/mnt/t/making-money python lab/venues/ctrader_costs.py
"""
import json
import os

os.environ.setdefault("ARTIFACT_ROOT", "/mnt/t/making-money")
from scripts import long_history as L
from zoo.panel import build_panel
from zoo.portfolio import BARS_PER_YEAR, cost_table

OUT = "docs/results/venues-ctrader-costs-2026-11-20.json"

paths = L.files()
p = build_panel(sorted(paths), loader=L.loader_for(paths))
for s, c in L.EXTRA_CLASS.items():
    p.loc[p.symbol == s, "asset_class"] = c
costs = cost_table(p)
for s, (c, fin) in L.EXTRA_COST.items():
    if s in costs.index:
        costs.loc[s, ["cost", "fin"]] = [c, fin / 260.0]
cls = p.groupby("symbol").asset_class.first()
costs["asset_class"] = cls
# cost = return cost per unit of |position change| = half a round trip.
costs["round_trip_bps"] = costs["cost"] * 2 * 1e4
costs["financing_pct_yr"] = [
    f * (260.0 if s in L.EXTRA_COST else BARS_PER_YEAR.get(c, 260.0)) * 100
    for s, f, c in zip(costs.index, costs["fin"], costs["asset_class"])]

tab = costs[["asset_class", "round_trip_bps", "financing_pct_yr", "cost_src"]].sort_values(
    ["asset_class", "round_trip_bps"])
by_cls = tab.groupby("asset_class")[["round_trip_bps", "financing_pct_yr"]].median().round(2)
print(tab.round(2).to_string())
print("\nmedian by class\n", by_cls.to_string())
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"per_symbol": tab.round(3).to_dict(orient="index"),
               "class_median": by_cls.to_dict(orient="index")}, fh, indent=1, default=str)
print("wrote", OUT)
