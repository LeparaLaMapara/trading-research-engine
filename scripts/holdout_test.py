"""The one-time holdout read for docs/results/prereg-neutral-trees-2026-09-20.md.

Three criteria, fixed before this ran: positive net Sharpe, above the 95th percentile of 150
instrument-label permutations on the same window, and positive in both holdout years.
"""
import json, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from config.instruments import extended_universe
from lab import registry
from research import episodes
from scripts.train_zoo import HOLDOUT_START, ann_factor, ensemble, oos_forecast, sharpe
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

N_NULL = 150
p = build_panel(extended_universe()); base = cost_table(p)
data_id = episodes.data_hash({"symbols": sorted(p["symbol"].unique()), "rows": len(p),
                              "last": str(p["date"].max())})
hold = p["date"] >= HOLDOUT_START
fut = base.copy(); fut["cost"] = 0.000128 / 2; fut["fin"] = 0.0
neutral = lambda f: f - f.groupby(p["date"]).transform("mean")

names = list(Z.BASELINES) + list(Z.RULES) + list(Z.LEARNED)
fc = {n: oos_forecast(n, p, None, data_id) for n in names}
fc["ens_ml"] = ensemble(Z.ENSEMBLES["ens_ml"], fc, p)

eid = registry.start("backtest", question="Does the market-neutral tree signal survive the "
                     "untouched holdout at futures-like costs?",
                     hypothesis="pre-registered: docs/results/prereg-neutral-trees-2026-09-20.md",
                     strategy="xgb_shallow_neutral", instruments="64", data_hash=data_id,
                     cost_model="1.3 bps round trip, no holding fee",
                     latency_model="not varied",
                     config_json={"window": "2024-09-16 to 2026-09-15", "nulls": N_NULL})

results = {}
for n in ["xgb_shallow", "extra_trees", "ens_ml"]:
    d = portfolio_returns(p, neutral(fc[n]), fut, hold)
    af = ann_factor(d)
    yearly = {int(y): sharpe(g["net"], af) for y, g in d.groupby(d.index.year)}
    results[n] = {"net": sharpe(d["net"], af), "yearly": yearly, "days": len(d)}
    print(f"{n:<14} holdout net Sharpe {results[n]['net']:+.3f}   by year "
          f"{ {k: round(v,2) for k,v in yearly.items()} }")

symbols = sorted(p["symbol"].unique())
src = pd.Series(fc["xgb_shallow"].to_numpy(),
                index=pd.MultiIndex.from_arrays([p["symbol"], p["date"]]))
nulls = []
t0 = time.time()
for seed in range(N_NULL):
    rng = np.random.default_rng(5000 + seed)
    mapping = dict(zip(symbols, rng.permutation(symbols)))
    key = pd.MultiIndex.from_arrays([p["symbol"].map(mapping), p["date"]])
    sh = pd.Series(src.reindex(key).to_numpy(), index=p.index)
    d = portfolio_returns(p, neutral(sh), fut, hold)
    nulls.append(sharpe(d["net"], ann_factor(d)))
a = np.array(nulls)
print(f"\nnull on the SAME window: mean {a.mean():+.3f} sd {a.std():.3f} "
      f"p95 {np.percentile(a,95):+.3f} max {a.max():+.3f}   ({time.time()-t0:.0f}s)")

r = results["xgb_shallow"]
c1 = r["net"] > 0
c2 = r["net"] > np.percentile(a, 95)
c3 = all(v > 0 for v in r["yearly"].values())
print(f"\ncriterion 1, positive net:              {'PASS' if c1 else 'FAIL'} ({r['net']:+.3f})")
print(f"criterion 2, above the 95th percentile: {'PASS' if c2 else 'FAIL'} "
      f"(bar {np.percentile(a,95):+.3f}, beats {(a < r['net']).mean()*100:.1f}% of draws)")
print(f"criterion 3, positive in both years:    {'PASS' if c3 else 'FAIL'} "
      f"({ {k: round(v,2) for k,v in r['yearly'].items()} })")
verdict = "SURVIVED" if (c1 and c2 and c3) else "FALSIFIED"
print(f"\nPRE-REGISTERED VERDICT: {verdict}")

out = {"results": results, "null_mean": float(a.mean()), "null_p95": float(np.percentile(a,95)),
       "null_max": float(a.max()), "criteria": {"positive": bool(c1), "above_null": bool(c2),
                                                "both_years": bool(c3)}, "verdict": verdict}
json.dump(out, open("docs/results/holdout-neutral-trees-2026-09-20.json","w"), indent=1, default=float)
registry.finish(eid, "complete", result_json=out, verdict=verdict,
                reason="pre-registered three-criterion test on the untouched holdout")
