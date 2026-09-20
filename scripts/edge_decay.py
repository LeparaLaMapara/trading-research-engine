"""Milestone 1: the empirical edge-decay curve for ONE strategy on ONE instrument.

    python -m scripts.edge_decay --symbol EURUSD --strategy ma_trend

The decision is formed at a daily bar's close, exactly as the backtest assumes. The fill is
then priced at the first hourly bar starting at or after decision time plus the delay. Delay
zero is the conventional assumption (filled at the price that produced the decision), which is
the thing being tested.

Buckets the data cannot price are reported as SKIPPED, never rounded to zero.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from backtest.run import load_bars, measured_cost
from lab import decay as D
from lab import registry
from research import episodes
from strategy.registry import build_strategy
from zoo.financing import fee_and_differential, load as load_swaps

#: Delays worth asking about. The sub-hour ones are asked deliberately: the run must SHOW that
#: hourly bars cannot answer them rather than quietly pretending they can.
DEFAULT_DELAYS = [0, 0.01, 1, 60, 900, 3600, 7200, 14400, 28800, 43200, 86400, 172800]


def build_signals(symbol: str, kind: str, params: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily decisions with the price that produced them, plus the hourly execution tape."""
    d1 = load_bars(symbol, "D1")
    h1 = load_bars(symbol, "H1")
    if d1.empty or h1.empty:
        raise SystemExit(f"need both D1 and H1 bars for {symbol}")
    strat = build_strategy(kind, params)
    pos = strat.generate_signals(d1).astype(float)
    # generate_signals gives the position HELD during bar t, decided from data up to t-1. So
    # the decision exists at the close of bar t-1, which is the start stamp of bar t, and the
    # price that produced it is bar t-1's close.
    sig = pd.DataFrame({"ts_close": d1["ts_utc"].astype(float),
                        "position": pos.to_numpy(),
                        "decision_price": d1["close"].shift(1).to_numpy()})
    sig = sig.dropna(subset=["decision_price"])
    # Only decisions that the hourly tape can actually price.
    sig = sig[sig["ts_close"] >= h1["ts_utc"].min()]
    return sig.reset_index(drop=True), h1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--strategy", default="ma_trend")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--delays", nargs="*", type=float, default=None)
    a = ap.parse_args()
    params = json.loads(a.params)
    delays = a.delays or DEFAULT_DELAYS
    t0 = time.time()

    sig, h1 = build_signals(a.symbol, a.strategy, params)
    ref = float(h1["close"].mean())
    cost = measured_cost(a.symbol, ref_price=ref).cost_per_unit_turnover()
    try:
        fee, _ = fee_and_differential(load_swaps()[a.symbol], ref)
    except (KeyError, OSError):
        fee = 0.01
    fin_per_day = fee / 365.0

    print(f"\n{a.strategy} on {a.symbol}: {len(sig):,} daily decisions, "
          f"{len(h1):,} hourly bars for pricing")
    print(f"cost per unit turnover {cost*1e4:.2f} bps, financing {fee*100:.2f}%/yr\n")

    eid = registry.start(
        "replay",
        question="At what execution delay does this strategy's edge disappear?",
        hypothesis="A daily trend signal is insensitive to delays of minutes but decays over hours.",
        strategy=a.strategy, strategy_version=json.dumps(params), instruments=a.symbol,
        period_start=pd.to_datetime(sig["ts_close"].min(), unit="s").isoformat(),
        period_end=pd.to_datetime(sig["ts_close"].max(), unit="s").isoformat(),
        data_hash=episodes.data_hash({"n_sig": len(sig), "n_h1": len(h1),
                                      "last": float(h1["ts_utc"].max())}),
        dataset_rows=len(sig),
        cost_model=f"measured spread+commission {cost*1e4:.2f}bps; financing {fee*100:.2f}%/yr",
        latency_model="H1 open at or after decision+delay; sub-hour buckets skipped",
        config_json={"delays_s": delays, "params": params}, seeds="none (deterministic)")

    curve = D.decay_curve(sig, h1, delays, cost, fin_per_day, "H1", bars_per_year=260.0)
    # Adaptive refinement: spend the extra runs only where the curve crosses zero.
    bracket = D.crossing_bracket(curve)
    extra, bracket = D.refine_bracket(sig, h1, bracket, cost, fin_per_day, "H1", 260.0)
    if not extra.empty:
        curve = pd.concat([curve, extra], ignore_index=True).sort_values("requested_delay_s")
    registry.save_decay(eid, a.strategy, a.symbol, curve)

    print(f"{'delay':>10}{'effective':>11}{'net ret':>10}{'sharpe':>8}{'EV/trade':>10}"
          f"{'win%':>7}{'PF':>7}{'maxDD':>8}{'trades':>8}   note")
    for _, r in curve.iterrows():
        d = r["requested_delay_s"]
        label = f"{d:.0f}s" if d < 3600 else f"{d/3600:.0f}h"
        if r.get("skipped"):
            print(f"{label:>10}{'-':>11}{'-':>10}{'-':>8}{'-':>10}{'-':>7}{'-':>7}{'-':>8}"
                  f"{'-':>8}   SKIPPED: {r['skipped'][:60]}")
            continue
        eff = r["effective_delay_s"]
        eff_s = f"{eff/3600:.1f}h" if eff >= 3600 else f"{eff:.0f}s"
        print(f"{label:>10}{eff_s:>11}{r['net_return']:>10.3f}{r['sharpe']:>8.2f}"
              f"{r['ev_per_trade']*1e4:>9.1f}b{r['win_rate']*100:>6.1f}{r['profit_factor']:>7.2f}"
              f"{r['max_dd']:>8.2f}{int(r['n_trades']):>8}")

    boot = D.bootstrap_crossing(sig, h1, delays, cost, fin_per_day, "H1", 260.0)
    thr, target, censored = D.survival_threshold(curve)
    target = D.operating_target(bracket)
    regime = D.regime_for(thr)
    feasible, why = D.feasible_from_here(thr)
    print()
    if bracket["status"] == "no_edge":
        print("LATENCY SURVIVAL THRESHOLD: none. The edge is not positive at ANY delay, "
              "including zero, so speed is not what is wrong with it.")
    elif bracket["status"] == "censored_right":
        print(f"LATENCY SURVIVAL THRESHOLD: > {bracket['lo']/3600:.1f} hours. The curve never "
              f"crossed zero inside the delays tested, so the grid ran out before the strategy "
              f"did.")
        print(f"CONSERVATIVE OPERATING TARGET: {target/3600:.2f} hours, at "
              f"{D.SAFETY_FACTOR:.0%} of the last delay shown to work")
    else:
        print(f"LATENCY SURVIVAL THRESHOLD: in ({bracket['lo']/3600:.1f} h, "
              f"{bracket['hi']/3600:.1f} h), narrowed by bisection to the data's "
              f"{bracket.get('resolution_limit_s', 3600)/3600:.0f} h resolution limit")
        print(f"CONSERVATIVE OPERATING TARGET: {target/3600:.2f} hours, at "
              f"{D.SAFETY_FACTOR:.0%} of the pessimistic end")
    if boot.get("reps"):
        if "crossing_median_s" in boot:
            print(f"BOOTSTRAP ({boot['reps']} block resamples): the crossing lands between "
                  f"{boot['crossing_p5_s']/3600:.0f}h and {boot['crossing_p95_s']/3600:.0f}h "
                  f"(median {boot['crossing_median_s']/3600:.0f}h). It never crosses inside the "
                  f"grid in {boot['never_crossed_pct']:.0f}% of resamples and shows no edge at "
                  f"any delay in {boot['no_edge_at_all_pct']:.0f}%.")
        else:
            print(f"BOOTSTRAP ({boot['reps']} resamples): no crossing in "
                  f"{boot['never_crossed_pct']:.0f}%, no edge at all in "
                  f"{boot['no_edge_at_all_pct']:.0f}%.")
        print("  The point bracket above is ONE realisation. Read the bootstrap interval.")
    print(f"SPEED REGIME (measured, not labelled): {regime}")
    print(f"FEASIBLE FROM THIS MACHINE: {feasible}. {why}")
    print(f"  (measured order path: min {D.MEASURED_ORDER_PATH_MS['min']:.0f}ms, "
          f"mean {D.MEASURED_ORDER_PATH_MS['mean']:.0f}ms, "
          f"max {D.MEASURED_ORDER_PATH_MS['max']:.0f}ms)")

    result = {"bracket": bracket, "bootstrap": boot, "threshold_s": thr,
              "threshold_censored": censored,
              "operating_target_s": target, "regime": regime,
              "feasible_from_here": feasible, "feasibility_note": why,
              "curve": curve.replace({np.nan: None}).to_dict("records")}
    verdict = ("NO_EDGE_AT_ANY_LATENCY" if thr is None
               else ("INFRASTRUCTURE_INFEASIBLE" if not feasible else "LATENCY_TOLERANT"))
    registry.finish(eid, "complete", result_json=result, verdict=verdict, reason=why,
                    information_gained=(
                        f"Measured how {a.strategy} on {a.symbol} decays with execution delay "
                        f"across {len([r for _, r in curve.iterrows() if not r.get('skipped')])} "
                        f"priceable buckets."),
                    next_experiment="Run the same sweep on every surviving candidate, then open "
                                    "the sub-hour band with M1 bars and a continuous tick logger.")
    out = f"docs/results/edge-decay-{a.strategy}-{a.symbol}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"experiment_id": eid, **result}, fh, indent=1, default=float)
    print(f"\nexperiment {eid} recorded; curve written to {out}  ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
