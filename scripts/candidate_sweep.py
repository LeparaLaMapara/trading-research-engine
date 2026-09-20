"""Mission steps 6 and 7: every candidate through ONE protocol, with the failure named.

Not a leaderboard. A leaderboard ranks by return and tells you nothing about why the bottom of
the list is at the bottom, which is the only part that changes what we do next.

    python -m scripts.candidate_sweep
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config.instruments import extended_universe
from lab import decompose as DC
from lab import registry
from research import episodes
from scripts.train_zoo import (DB, HOLDOUT_START, ann_factor, ensemble, oos_forecast, sharpe)
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

#: Our measured decision-to-order path: about 1s to the broker, plus a ~1s reconcile inside the
#: risk check (measured 2026-09-20 via lab.lifecycle). Two seconds is the honest operating
#: latency, and hourly data cannot price it, which is exactly what the bound is for.
OPERATING_DELAY_S = 2.0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    p = build_panel(extended_universe())
    costs = cost_table(p)
    data_id = episodes.data_hash({"symbols": sorted(p["symbol"].unique()), "rows": len(p),
                                  "last": str(p["date"].max())})
    dev = (p["date"] >= pd.Timestamp("2017-01-01")) & (p["date"] < HOLDOUT_START)

    names = list(Z.BASELINES) + list(Z.RULES) + list(Z.LEARNED)
    fc = {n: oos_forecast(n, p, None, data_id) for n in names}
    for e, members in Z.ENSEMBLES.items():
        fc[e] = ensemble(members, fc, p)

    # Latency evidence, from the edge-decay experiments already in the registry.
    conn = sqlite3.connect(DB)
    decay = pd.read_sql_query(
        "SELECT strategy, instrument, requested_delay_s, effective_delay_s, skipped, sharpe "
        "FROM edge_decay", conn)
    zoo_rows = pd.read_sql_query(
        "SELECT model, dsr, years_positive, years_total, n_obs FROM zoo_results", conn)
    conn.close()
    zoo_meta = zoo_rows.set_index("model").to_dict("index")

    eid = registry.start(
        "backtest", question="What is each candidate's failure mode, not its rank?",
        hypothesis="Most candidates fail for cost reasons, not predictive ones.",
        instruments=f"{p['symbol'].nunique()} instruments", data_hash=data_id,
        dataset_rows=len(p), cost_model="measured spread (p75 where coverage is thin) + swaps",
        latency_model=f"operating delay {OPERATING_DELAY_S}s; bounded by the finest priceable "
                      f"bucket", config_json={"operating_delay_s": OPERATING_DELAY_S})

    rows = []
    for name, f in fc.items():
        if name == "cash":
            continue
        d = portfolio_returns(p, f, costs, dev)
        af = ann_factor(d)
        yearly = {int(y): sharpe(g["net"], af) for y, g in d.groupby(d.index.year)}
        meta = zoo_meta.get(name, {})

        # Latency evidence for this candidate, if any edge-decay curve exists for it.
        cur = decay[decay["strategy"] == name]
        lat = DC.latency_cost_from_curve(cur, OPERATING_DELAY_S) if not cur.empty else None
        bound, bound_at = DC.bound_latency_cost(cur) if not cur.empty else (None, None)

        comp = DC.components(d, af, lat)
        # Turnover is what the PORTFOLIO actually traded, after the buffer; the raw forecast
        # diff counts intentions, including ones the buffer suppressed.
        turnover = float(d["turn"].mean() * af)
        trades = int(round(turnover * (len(d) / af)))
        verdict, why = DC.classify(comp, trades, len(d),
                                   sum(1 for v in yearly.values() if v > 0), len(yearly),
                                   meta.get("dsr"), turnover_per_year=turnover)
        rows.append({"model": name, **comp, "verdict": verdict, "why": why,
                     "n_trades": trades, "turnover_per_year": turnover, "n_obs": len(d),
                     "years_positive": sum(1 for v in yearly.values() if v > 0),
                     "years_total": len(yearly), "dsr": meta.get("dsr"),
                     "latency_bound": bound, "latency_bound_at_s": bound_at})

    rows.sort(key=lambda r: (-r["net_sharpe"]))
    print(f"\n{'model':<22}{'gross':>8}{'costs':>8}{'fin':>7}{'net':>8}{'trades':>8}   verdict")
    for r in rows:
        print(f"{r['model']:<22}{r['gross_sharpe']:>8.2f}{r['spread_and_fees']:>8.2f}"
              f"{r['financing']:>7.2f}{r['net_sharpe']:>8.2f}{r['n_trades']:>8}   {r['verdict']}")

    tally = Counter(r["verdict"] for r in rows)
    print("\nfailure modes:")
    for v, n in tally.most_common():
        print(f"  {v:<32}{n}")

    lat_known = [r for r in rows if r["latency_cost"] is not None]
    print(f"\nlatency cost measured for {len(lat_known)} of {len(rows)} candidates at the "
          f"{OPERATING_DELAY_S:g}s operating delay.")
    bounds = [r for r in rows if r["latency_bound"] is not None]
    if bounds:
        b = bounds[0]
        print(f"For those with a decay curve, the UPPER BOUND on latency cost is "
              f"{b['latency_bound']:.2f} Sharpe, and that is the cost of being "
              f"{b['latency_bound_at_s']/3600:.0f} HOUR(S) late, not {OPERATING_DELAY_S:g}s. "
              f"Hourly data cannot price a two-second delay, so the true cost is unmeasured "
              f"and bounded far below this.")

    out = {"operating_delay_s": OPERATING_DELAY_S, "data_hash": data_id,
           "verdict_counts": dict(tally), "rows": rows}
    with open("docs/results/candidate-sweep-2026-09-20.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float)
    registry.finish(eid, "complete", result_json=out,
                    verdict=max(tally, key=tally.get),
                    reason=f"{tally.most_common(1)[0][1]} of {len(rows)} candidates share the "
                           f"dominant failure mode",
                    information_gained="Each candidate now carries a diagnosed failure mode "
                                       "rather than a rank.",
                    next_experiment="Test whether anything computable from top-of-book alone "
                                    "beats the cost floor at 1 to 60 seconds (H5).")
    print(f"\nexperiment {eid}  ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
