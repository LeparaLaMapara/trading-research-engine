"""Queue item 3: do the same signals survive somewhere cheaper?

The candidate sweep found 14 of 20 candidates are EDGE_DESTROYED_BY_COSTS: real gross signal,
eaten by friction. That makes the venue, not the model, the variable worth changing. This
re-prices the IDENTICAL forecasts under three cost regimes and asks which candidates flip.

    python -m scripts.venue_rescore

Regimes, with their sources stated because they are estimates of different quality:

  cfd_broker   MEASURED. Spread from our own telemetry (75th percentile where coverage is thin)
               plus commission, plus the broker's own swap fee as a holding cost.
  cme_micro    ESTIMATED. Micro futures: about 0.26 bps commission and 0.38 bps of spread per
               side on a ~$33k MES contract, and NO holding fee, because a future's financing
               is already in its price rather than charged as a fee. Margin, not modelled here,
               is roughly R15,000 to R25,000 per contract, which is the real barrier.
  valr_perp    ESTIMATED from the published fee schedule: about 14 bps round trip, R10 minimum
               order, and funding INSTEAD of a fixed holding fee. Funding is not modelled: it
               is paid or received depending on side and can be either sign, so charging a
               constant would be inventing a number.

The instrument caveat is stated loudly in the output: our panel is CFDs, and a futures venue
would not offer all 64. This re-score answers "would these signals survive that cost
structure", not "we can trade this basket there tomorrow".
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from collections import Counter

import pandas as pd

warnings.filterwarnings("ignore")

from config.instruments import extended_universe
from lab import decompose as DC
from lab import registry
from research import episodes
from scripts.train_zoo import HOLDOUT_START, ann_factor, ensemble, oos_forecast, sharpe
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

#: (round-trip cost as a fraction of notional, annual holding fee, note)
REGIMES = {
    "cfd_broker": (None, None, "measured: our own spread telemetry + broker swap fee"),
    "cme_micro": (0.000128, 0.0, "estimated: ~1.3 bps round trip, no holding fee"),
    "valr_perp": (0.0014, 0.0, "estimated: 14 bps round trip, funding not modelled"),
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    p = build_panel(extended_universe())
    base = cost_table(p)
    data_id = episodes.data_hash({"symbols": sorted(p["symbol"].unique()), "rows": len(p),
                                  "last": str(p["date"].max())})
    dev = (p["date"] >= pd.Timestamp("2017-01-01")) & (p["date"] < HOLDOUT_START)

    names = list(Z.BASELINES) + list(Z.RULES) + list(Z.LEARNED)
    fc = {n: oos_forecast(n, p, None, data_id) for n in names}
    for e, members in Z.ENSEMBLES.items():
        fc[e] = ensemble(members, fc, p)
    fc.pop("cash", None)

    eid = registry.start(
        "backtest", question="Do the same signals survive at a venue with no holding fee?",
        hypothesis="The pooled ML signals are cost-killed, so removing the holding fee should "
                   "flip several from negative to positive.",
        instruments=f"{p['symbol'].nunique()} CFD instruments (proxy for futures/perp costs)",
        data_hash=data_id, dataset_rows=len(p),
        cost_model=json.dumps({k: v[2] for k, v in REGIMES.items()}),
        latency_model="not varied",
        config_json={"regimes": {k: v[:2] for k, v in REGIMES.items()}})

    results: dict[str, dict] = {}
    for regime, (rt_cost, holding, note) in REGIMES.items():
        costs = base.copy()
        if rt_cost is not None:
            costs["cost"] = rt_cost / 2.0        # cost_per_unit_turnover is per half turn
            costs["fin"] = holding / 260.0
        out = {}
        for name, f in fc.items():
            d = portfolio_returns(p, f, costs, dev)
            af = ann_factor(d)
            yearly = {int(y): sharpe(g["net"], af) for y, g in d.groupby(d.index.year)}
            comp = DC.components(d, af, None)
            turnover = float(d["turn"].mean() * af)
            verdict, _ = DC.classify(comp, int(round(turnover * len(d) / af)), len(d),
                                     sum(1 for v in yearly.values() if v > 0), len(yearly),
                                     None, turnover_per_year=turnover)
            out[name] = {"net": comp["net_sharpe"], "gross": comp["gross_sharpe"],
                         "costs": comp["spread_and_fees"], "fin": comp["financing"],
                         "verdict": verdict,
                         "years_positive": sum(1 for v in yearly.values() if v > 0),
                         "years_total": len(yearly)}
        results[regime] = out
        print(f"  scored {regime}: {note}")

    order = sorted(fc, key=lambda n: -results["cme_micro"][n]["net"])
    print(f"\n{'model':<22}{'CFD net':>9}{'futures':>9}{'perp':>8}{'change':>9}"
          f"   verdict at futures costs")
    for n in order:
        a = results["cfd_broker"][n]["net"]
        b = results["cme_micro"][n]["net"]
        c = results["valr_perp"][n]["net"]
        print(f"{n:<22}{a:>9.2f}{b:>9.2f}{c:>8.2f}{b - a:>+9.2f}   "
              f"{results['cme_micro'][n]['verdict']}")

    flips = [n for n in fc if results["cfd_broker"][n]["net"] <= 0 < results["cme_micro"][n]["net"]]
    tally = Counter(results["cme_micro"][n]["verdict"] for n in fc)
    print(f"\ncandidates that flip from negative to positive when the holding fee goes: "
          f"{len(flips)}")
    if flips:
        print("  " + ", ".join(flips))
    print("\nfailure modes at futures-like costs:")
    for v, k in tally.most_common():
        print(f"  {v:<32}{k}")
    print("\nCAVEAT, and it is not small: the panel is CFDs. A futures venue would not list all "
          f"{p['symbol'].nunique()} of these instruments, and margin per micro contract is "
          "roughly R15,000 to R25,000, which the R2,000 account cannot hold. This answers "
          "whether the SIGNALS survive that cost structure, not whether we can trade them "
          "there.")

    best = max(fc, key=lambda n: results["cme_micro"][n]["net"])
    out = {"data_hash": data_id, "flips": flips, "best_at_futures_costs": best,
           "results": results}
    with open("docs/results/venue-rescore-2026-09-20.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float)
    registry.finish(eid, "complete", result_json=out,
                    verdict="FLIPPED" if flips else "NO_FLIP",
                    reason=f"{len(flips)} candidates cross zero when the holding fee is removed",
                    information_gained="Whether the cost-killed candidates are merely expensive "
                                       "or actually weak.",
                    next_experiment="If several flip, price the margin and instrument coverage "
                                    "of the cheapest venue that lists enough of them.")
    print(f"\nexperiment {eid}  ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
