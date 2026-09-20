"""Randomisation test: is the market-neutral tree signal outside the noise floor?

A Sharpe over 8 years has a standard error near 0.35, so 0.6 is under two standard errors and
cannot be judged by eye. The honest null is not a formula: it is the SAME pipeline, the same
costs, the same buffer and the same universe, driven by forecasts with no information. Run that
many times and the distribution of Sharpes IS the noise floor.
"""
import warnings, numpy as np, pandas as pd, json, time; warnings.filterwarnings("ignore")
from config.instruments import extended_universe
from scripts.train_zoo import HOLDOUT_START, ann_factor, ensemble, oos_forecast, sharpe
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns
from research import episodes

N_NULL = 150
p = build_panel(extended_universe()); base = cost_table(p)
data_id = episodes.data_hash({"symbols": sorted(p["symbol"].unique()), "rows": len(p), "last": str(p["date"].max())})
dev = (p.date >= pd.Timestamp("2017-01-01")) & (p.date < HOLDOUT_START)
fut = base.copy(); fut["cost"] = 0.000128/2; fut["fin"] = 0.0

def neutral(f):
    return f - f.groupby(p["date"]).transform("mean")

names = list(Z.BASELINES)+list(Z.RULES)+list(Z.LEARNED)
fc = {n: oos_forecast(n,p,None,data_id) for n in names}
fc["ens_ml"] = ensemble(Z.ENSEMBLES["ens_ml"], fc, p)
real = {}
for n in ["xgb_shallow","extra_trees","ens_ml","ridge_pooled"]:
    d = portfolio_returns(p, neutral(fc[n]), fut, dev)
    real[n] = sharpe(d["net"], ann_factor(d))

# THE NULL MUST MATCH TURNOVER. The first version shuffled forecasts across instruments WITHIN
# each date, which destroys the time-series persistence of a forecast and makes the null trade
# far more than the real strategy, so it pays far more costs. The null then averaged -1.33
# Sharpe and everything "beat" it: a comparison against a strategy handicapped by construction.
#
# Instead permute the INSTRUMENT LABELS once per draw, so each instrument receives another
# instrument's whole forecast path. Persistence, turnover and the cost profile are preserved;
# only the pairing between forecast and instrument is destroyed, which is precisely the claim
# under test: does this model know WHICH instrument to hold?
template = fc["xgb_shallow"]
symbols = sorted(p["symbol"].unique())
nulls = []
t0 = time.time()
for seed in range(N_NULL):
    rng = np.random.default_rng(1000 + seed)
    # Shuffle the real forecasts WITHIN each date across instruments: destroys which instrument
    # the model picked while preserving the daily distribution of forecast sizes exactly.
    mapping = dict(zip(symbols, rng.permutation(symbols)))
    key = pd.MultiIndex.from_arrays([p["symbol"].map(mapping), p["date"]])
    src = pd.Series(template.to_numpy(),
                    index=pd.MultiIndex.from_arrays([p["symbol"], p["date"]]))
    shuffled = pd.Series(src.reindex(key).to_numpy(), index=p.index)
    d = portfolio_returns(p, neutral(shuffled), fut, dev)
    nulls.append(sharpe(d["net"], ann_factor(d)))
    if seed % 25 == 0:
        print(f"  {seed}/{N_NULL}  ({time.time()-t0:.0f}s)", flush=True)

a = np.array(nulls)
print(f"\nnull distribution over {N_NULL} instrument-shuffles, market-neutral, futures costs:")
print(f"  mean {a.mean():+.3f}  sd {a.std():.3f}  p5 {np.percentile(a,5):+.3f}  "
      f"p95 {np.percentile(a,95):+.3f}  max {a.max():+.3f}")
print()
for n, v in sorted(real.items(), key=lambda kv: -kv[1]):
    pct = (a < v).mean() * 100
    verdict = "OUTSIDE the noise floor" if pct >= 95 else "inside the noise floor"
    print(f"  {n:<16}{v:+.3f}   beats {pct:5.1f}% of random shuffles   {verdict}")
json.dump({"nulls": list(map(float, a)), "real": real, "null_design": "instrument-label permutation, turnover preserved"}, open("docs/results/null-test-2026-09-20.json","w"), indent=1)
