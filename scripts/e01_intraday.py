"""Run E01 exactly as pre-registered (docs/programme/E01-intraday-momentum-prereg.md).

    python -m scripts.e01_intraday
    python -m scripts.e01_intraday --experiment E02     # same rule, E02's pre-registration

Writes docs/results/E01-intraday-momentum.json and prints the verdict. Records one trial in
data/research.db so the engine's N stays honest.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

from backtest.run import measured_cost
from backtest.walkforward import deflated_sharpe_ratio
from config.instruments import asset_class_of
from lab import intraday as I
from research import episodes

MARKET_DB = "data/market.db"
N_NULL = 200

#: Each experiment that reuses this rule, exactly as its pre-registration states it.
#: symbols None means every symbol with hourly bars; end is exclusive (UTC date).
EXPERIMENTS = {
    # E01 used the bars stored when it ran: first bar 2020-09-16 20:00 UTC.
    # Older bars fetched later for E02 must not leak into a re-run of E01, and neither may
    # bars fetched after it ran.
    "E01": dict(out="docs/results/E01-intraday-momentum.json", symbols=None,
                start="2020-09-16T20:00", end="2026-09-16",   # the bars stored when it ran
                years=(2021, 2026), min_years_positive=4, n_trials=296),
    "E02": dict(out="docs/results/E02-intraday-metals-energy.json",
                symbols=["XAUUSD", "XAGUSD", "XAUEUR", "XTIUSD", "XBRUSD"],
                start=None, end="2020-09-17", years=(2015, 2019), min_years_positive=3, n_trials=297),
}
COMMISSION_SIDE = 0.000035


def load(symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    with sqlite3.connect(MARKET_DB) as c:
        df = pd.read_sql_query(
            "SELECT ts_utc, open FROM bars WHERE symbol=? AND period='H1' ORDER BY ts_utc",
            c, params=(symbol,))
    if start is not None:
        df = df[df["ts_utc"] >= pd.Timestamp(start, tz="UTC").timestamp()]
    if end is not None:
        df = df[df["ts_utc"] < pd.Timestamp(end, tz="UTC").timestamp()]
    return df


def round_trip_cost(symbol: str, ref: float, mult: float = 1.0) -> tuple[float, str]:
    cm = measured_cost(symbol, ref_price=ref)
    spread = cm.spread_pips * cm.pip_size / ref            # one full spread per round trip
    return mult * (spread + 2 * COMMISSION_SIDE), f"{cm.spread_pips:g} pips"


def build(days: dict[str, pd.DataFrame], mult: float = 1.0):
    per, meta, costs = {}, {}, {}
    for s, d in days.items():
        pos = I.positions(d)
        I.assert_flat_at_rollover(I.hourly_position_path(d, pos))
        cost, src = round_trip_cost(s, float(d["entry"].median()), mult)
        per[s], costs[s] = I.instrument_returns(d, pos, cost), cost
        meta[s] = {"days": int(len(d)), "cost_rt_bps": round(cost * 1e4, 3), "spread": src}
    return per, meta, costs


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", default="E01", choices=sorted(EXPERIMENTS))
    ap.add_argument("--check", metavar="PATH",
                    help="reproduce only: write the result to PATH and record no trial")
    args = ap.parse_args()
    eid = args.experiment
    cfg = EXPERIMENTS[eid]
    with sqlite3.connect(MARKET_DB) as c:
        symbols = cfg["symbols"] or [r[0] for r in c.execute(
            "SELECT DISTINCT symbol FROM bars WHERE period='H1' ORDER BY symbol")]
    days = {s: I.day_table(load(s, cfg["start"], cfg["end"])) for s in symbols}
    days = {s: d for s, d in days.items() if len(d) >= I.MIN_HISTORY + 5}
    print(f"{eid} on {len(days)} of {len(symbols)} symbols")
    per, meta, costs = build(days)
    net, gross = I.portfolio(per, "net"), I.portfolio(per, "gross")
    sr_net, sr_gross = I.ann_sharpe(net), I.ann_sharpe(gross)
    print(f"  net Sharpe {sr_net:.3f}  gross {sr_gross:.3f}  days {len(net)}")

    # C2: random sign per instrument-day, same schedule, weights and costs.
    nulls = []
    for seed in range(N_NULL):
        rng = np.random.default_rng(seed)
        pn = {s: I.instrument_returns(
                  days[s], pd.Series(rng.choice([-1.0, 1.0], size=len(days[s])),
                                     index=days[s].index), costs[s])
              for s in per}
        nulls.append(I.ann_sharpe(I.portfolio(pn, "net")))
    p95 = float(np.percentile(nulls, 95))

    # C3: the pre-registered calendar years, and the last 12 months.
    y0, y1 = cfg["years"]
    yearly = net.groupby(net.index.year).sum()
    years = {int(y): float(v) for y, v in yearly.items() if y0 <= y <= y1}
    last12 = float(net[net.index > net.index[-1] - pd.Timedelta(days=365)].sum())

    # C4: doubled costs.
    per2, _, _ = build(days, mult=2.0)
    sr_double = I.ann_sharpe(I.portfolio(per2, "net"))

    crit = {
        "C1_net_sharpe_positive": sr_net > 0,
        "C2_beats_null_p95": sr_net > p95,
        "C3_years_and_last_12m": (sum(v > 0 for v in years.values())
                                  >= cfg["min_years_positive"] and last12 > 0),
        "C4_survives_double_costs": sr_double > 0,
    }
    verdict = "PASS" if all(crit.values()) else "FAIL"

    by_class = {}
    for cls in sorted({asset_class_of(s) or "other" for s in per}):
        sub = {s: per[s] for s in per if (asset_class_of(s) or "other") == cls}
        by_class[cls] = round(I.ann_sharpe(I.portfolio(sub, "net")), 3)

    std_trials = 1.0 / np.sqrt(len(net))       # zero-skill spread of per-observation Sharpes
    dsr = deflated_sharpe_ratio(net, cfg["n_trials"], std_trials)
    data_id = episodes.data_hash({"symbols": sorted(per), "days": len(net),
                                  "last": str(net.index[-1])})
    res = {
        "experiment": eid, "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data_hash": data_id, "symbols": len(per),
        "sample": [str(net.index[0].date()), str(net.index[-1].date())],
        "portfolio_days": int(len(net)),
        "net_sharpe": round(sr_net, 3), "gross_sharpe": round(sr_gross, 3),
        "null_p95": round(p95, 3), "null_mean": round(float(np.mean(nulls)), 3),
        "net_by_year": {k: round(v, 4) for k, v in years.items()},
        "net_last_12m": round(last12, 4),
        "net_sharpe_double_costs": round(sr_double, 3),
        "net_sharpe_by_class": by_class,
        f"deflated_sharpe_at_N{cfg['n_trials']}": round(dsr, 3),
        "symbols_dropped": sorted(set(symbols) - set(per)),
        "criteria": crit, "verdict": verdict, "instruments": meta,
    }
    with open(args.check or cfg["out"], "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    if args.check:
        print(f"{eid} verdict: {verdict} (check run, no trial recorded)")
        return 0

    from research.registry import FailureRegistry
    reg = FailureRegistry()
    tid = reg.record_trial("intraday_momentum", {"entry": 12, "exit": 20}, "PORTFOLIO", "H1",
                           stage=f"programme_{eid}", per_obs_sharpe=float(net.mean() / net.std()),
                           n_bars=int(len(net)))
    reg.set_trial_dsr(tid, dsr)

    print(json.dumps({k: v for k, v in res.items() if k != "instruments"}, indent=1))
    print(f"{eid} verdict: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
