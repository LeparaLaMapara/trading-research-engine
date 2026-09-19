"""Train and score the whole model zoo under the pre-registered protocol.

Protocol: docs/results/zoo-preregistration-2026-09-19.md. Summary: 64 instrument daily panel,
walk forward by calendar year 2017-2024 with a 10 day embargo, identical position
construction and costs for every model, portfolio level scoring, deflated Sharpe against the
honest trial count. The holdout (from 2024-09-16) is touched once, at the end, only for the
development champion and the pre-declared comparison set.

Run:  python -m scripts.train_zoo            # dev phase, resumable (forecasts cached)
      python -m scripts.train_zoo --holdout  # the one-time holdout read

Resumable: each model's out-of-sample forecast is cached under ARTIFACT_ROOT, so a crash
costs one model, not the run.
"""
from __future__ import annotations

import argparse
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
from config.instruments import extended_universe
from research import episodes
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, per_instrument_net, portfolio_returns

DB = "data/research.db"
HOLDOUT_START = pd.Timestamp("2024-09-16")
DEV_YEARS = list(range(2017, 2025))
EMBARGO = pd.Timedelta(days=10)
CACHE = os.path.join(os.environ.get("ARTIFACT_ROOT", r"T:\making-money"), "sweeps",
                     "zoo-2026-09-19")
PROGRAMME = "zoo-2026-09-19"
COMPARISON = ("cash", "long_risk_parity")

SCHEMA = """
CREATE TABLE IF NOT EXISTS zoo_results (
    run TEXT, model TEXT, family TEXT, dev_sharpe REAL, gross_sharpe REAL,
    per_obs_sharpe REAL, n_obs INTEGER, years_positive INTEGER, years_total INTEGER,
    yearly_json TEXT, max_dd REAL, turnover REAL, cost_sharpe REAL, dsr REAL,
    holdout_sharpe REAL, verdict TEXT, ran_at REAL,
    PRIMARY KEY (run, model)
);
"""


def family_of(name: str) -> str:
    for fam, d in (("baseline", Z.BASELINES), ("rule", Z.RULES), ("learned", Z.LEARNED),
                   ("ensemble", Z.ENSEMBLES)):
        if name in d:
            return fam
    return "?"


def ann_factor(daily: pd.DataFrame) -> float:
    span = (daily.index.max() - daily.index.min()).days / 365.25
    return len(daily) / span if span > 0 else 260.0


def sharpe(x: pd.Series, af: float) -> float:
    return float(x.mean() / x.std() * np.sqrt(af)) if x.std() > 0 else 0.0


def max_dd(x: pd.Series) -> float:
    eq = (x / x.std() * 0.10 / np.sqrt(260)).cumsum()     # at 10% annual vol, additive
    return float((eq - eq.cummax()).min())


def scaled(raw_te: np.ndarray, raw_tr: np.ndarray) -> np.ndarray:
    s = np.nanmean(np.abs(raw_tr))
    return np.clip(np.nan_to_num(raw_te / s if s > 0 else raw_te * 0), -2, 2)


def oos_forecast(name: str, p: pd.DataFrame, seq) -> pd.Series:
    """Walk forward out-of-sample forecast over the development years (NaN elsewhere)."""
    path = os.path.join(CACHE, f"{name}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)["f"].set_axis(p.index)
    fn = {**Z.BASELINES, **Z.RULES, **Z.LEARNED}[name]
    out = pd.Series(np.nan, index=p.index)
    for y in DEV_YEARS + ["holdout"]:
        if y == "holdout":
            start, end = HOLDOUT_START, p["date"].max() + pd.Timedelta(days=1)
        else:
            start = pd.Timestamp(f"{y}-01-01")
            end = min(pd.Timestamp(f"{y + 1}-01-01"), HOLDOUT_START)
        tr = p["date"] < (start - EMBARGO)
        te = (p["date"] >= start) & (p["date"] < end)
        if te.sum() == 0:
            continue
        t0 = time.time()
        if name in Z.LEARNED:
            res = fn(p, tr, te, seq) if name == "gru_seq" else fn(p, tr, te)
            raw_te, raw_tr = res
        else:
            raw_te = fn(p, tr, te)
            raw_tr = fn(p, tr, tr) if name not in ("cash",) else np.ones(1)
            if name in ("long_risk_parity", "random_sign", "tsmom_12m"):
                raw_tr = np.ones(1)            # already unit forecasts
        out[te] = scaled(np.asarray(raw_te, float), np.asarray(raw_tr, float))
        print(f"    {name:<22}{str(y):>8}  {te.sum():>6} rows  {time.time() - t0:5.1f}s",
              flush=True)
    os.makedirs(CACHE, exist_ok=True)
    pd.DataFrame({"f": out.to_numpy()}).to_parquet(path)
    return out


def ensemble(members: list[str], fc: dict[str, pd.Series], p: pd.DataFrame) -> pd.Series:
    """Equal-weight average of scaled forecasts, rescaled per year using ONLY prior years'
    out-of-sample magnitude (first year unscaled), so no future magnitude leaks in."""
    avg = pd.concat([fc[m] for m in members], axis=1).mean(axis=1)
    out = avg.copy()
    year = p["date"].dt.year.where(p["date"] < HOLDOUT_START, 9999)
    for y in sorted(year.unique()):
        prior = avg[(year < y) & avg.notna()]
        k = 1.0 / prior.abs().mean() if len(prior) and prior.abs().mean() > 0 else 1.0
        out[year == y] = (avg[year == y] * k).clip(-2, 2)
    return out


def honest_n(conn) -> int:
    n = 0
    for q in ("SELECT count(*) FROM sweep_results", "SELECT count(*) FROM trials"):
        try:
            n += conn.execute(q).fetchone()[0]
        except sqlite3.Error:
            pass
    return n


def block_bootstrap_sharpe(x: np.ndarray, af: float, block=20, reps=2000, seed=7):
    rng = np.random.default_rng(seed)
    n = len(x)
    out = np.empty(reps)
    for i in range(reps):
        starts = rng.integers(0, n - block, size=n // block + 1)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        s = x[idx]
        out[i] = s.mean() / s.std() * np.sqrt(af) if s.std() > 0 else 0.0
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()

    t0 = time.time()
    print("building panel...", flush=True)
    p = build_panel(extended_universe())
    costs = cost_table(p)
    print(f"panel: {len(p):,} rows, {p['symbol'].nunique()} instruments, "
          f"{p['date'].min().date()} to {p['date'].max().date()}  ({time.time() - t0:.0f}s)")
    data_id = episodes.data_hash({"symbols": sorted(p["symbol"].unique()),
                                  "rows": len(p), "last": str(p["date"].max())})

    names = list(Z.BASELINES) + list(Z.RULES) + list(Z.LEARNED)
    if a.only:
        names = [n for n in names if n in a.only]
    seq = Z.sequences(p) if "gru_seq" in names else None
    fc = {}
    for n in names:
        print(f"  {n}", flush=True)
        fc[n] = oos_forecast(n, p, seq)
    if not a.only:
        for e, members in Z.ENSEMBLES.items():
            fc[e] = ensemble(members, fc, p)

    dev = (p["date"] >= pd.Timestamp("2017-01-01")) & (p["date"] < HOLDOUT_START)
    hold = p["date"] >= HOLDOUT_START
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)

    rows = []
    for n, f in fc.items():
        d = portfolio_returns(p, f, costs, dev)
        af = ann_factor(d)
        yearly = {int(y): round(sharpe(g["net"], af), 3) for y, g in d.groupby(d.index.year)}
        rows.append({"model": n, "family": family_of(n), "dev_sharpe": sharpe(d["net"], af),
                     "gross_sharpe": sharpe(d["gross"], af),
                     "per_obs_sharpe": wf.per_obs_sharpe(d["net"]), "n_obs": len(d),
                     "years_positive": sum(v > 0 for v in yearly.values()),
                     "years_total": len(yearly), "yearly": yearly,
                     "max_dd": max_dd(d["net"]) if d["net"].std() > 0 else 0.0,
                     "turnover": float(d["turn"].mean() * af),
                     "cost_sharpe": float((d["tcost"] + d["fcost"]).mean() / d["gross"].std()
                                          * np.sqrt(af)) if d["gross"].std() > 0 else 0.0,
                     "af": af, "daily": d})

    # Honest N: every candidate this engine has ever scored, INCLUDING today's zoo rows.
    now = time.time()
    # Re-scoring the same candidates (e.g. the holdout pass) is not a new trial: replace, never add.
    conn.execute("DELETE FROM trials WHERE variant LIKE ?", (f"{PROGRAMME}:%",))
    for r in rows:
        if r["model"] == "cash":
            continue
        conn.execute("INSERT INTO trials (variant, strategy_kind, symbol, period, stage, "
                     "per_obs_sharpe, n_bars, created_ts) VALUES (?,?,?,?,?,?,?,?)",
                     (f"{PROGRAMME}:{r['model']}", r["model"], "PORTFOLIO64", "D1", "zoo_dev",
                      r["per_obs_sharpe"], r["n_obs"], now))
    conn.commit()
    N = honest_n(conn)
    spread = float(np.std([r["per_obs_sharpe"] for r in rows if r["model"] != "cash"]))
    sr0 = wf.expected_max_sharpe(spread, N)

    for r in rows:
        r["dsr"] = wf.deflated_sharpe_ratio(r["daily"]["net"], N, spread) \
            if r["model"] != "cash" else 0.0

    rows.sort(key=lambda r: r["dev_sharpe"], reverse=True)
    print(f"\nhonest N = {N}; Sharpe spread across zoo (per obs) = {spread:.5f}; "
          f"luck bar (annualised) = {sr0 * np.sqrt(rows[0]['af']):.3f}\n")
    print(f"{'model':<22}{'family':<10}{'dev net':>8}{'gross':>8}{'cost':>7}{'yrs+':>6}"
          f"{'maxDD':>8}{'turn/yr':>8}{'DSR':>7}")
    for r in rows:
        print(f"{r['model']:<22}{r['family']:<10}{r['dev_sharpe']:>8.3f}{r['gross_sharpe']:>8.3f}"
              f"{r['cost_sharpe']:>7.3f}{r['years_positive']:>3}/{r['years_total']:<2}"
              f"{r['max_dd']:>8.2f}{r['turnover']:>8.1f}{r['dsr']:>7.3f}")

    champ = next(r for r in rows if r["model"] not in Z.BASELINES)
    best_rule = next(r for r in rows if r["family"] == "rule")
    ci = block_bootstrap_sharpe(champ["daily"]["net"].to_numpy(), champ["af"])
    print(f"\nchampion: {champ['model']}  dev Sharpe {champ['dev_sharpe']:.3f}  "
          f"95% block-bootstrap CI [{ci[0]:.2f}, {ci[1]:.2f}]  DSR {champ['dsr']:.3f}")

    holdout = {}
    if a.holdout:
        for n in dict.fromkeys([champ["model"], best_rule["model"], *COMPARISON]):
            d = portfolio_returns(p, fc[n], costs, hold)
            holdout[n] = sharpe(d["net"], ann_factor(d))
            print(f"  HOLDOUT {n:<22} net Sharpe {holdout[n]:.3f}  ({len(d)} days)")

    for r in rows:
        passed = (r["dsr"] >= 0.95 and r["years_positive"] >= 5
                  and holdout.get(r["model"], -1) > 0)
        if r["model"] == "cash":
            verdict = "UNEVALUABLE"
        elif passed:
            verdict = "SURVIVED"
        elif r["dev_sharpe"] <= 0:
            verdict = "FALSIFIED"
        elif r["cost_sharpe"] > r["gross_sharpe"] > 0:
            verdict = "TOO_EXPENSIVE"
        else:
            verdict = "UNDERPOWERED"   # positive but not distinguishable from luck
        r["verdict"] = verdict
        conn.execute("INSERT OR REPLACE INTO zoo_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (PROGRAMME, r["model"], r["family"], r["dev_sharpe"], r["gross_sharpe"],
                      r["per_obs_sharpe"], r["n_obs"], r["years_positive"], r["years_total"],
                      json.dumps(r["yearly"]), r["max_dd"], r["turnover"], r["cost_sharpe"],
                      r["dsr"], holdout.get(r["model"]), verdict, now))
    conn.commit()

    pooled = {r["model"]: round(r["dev_sharpe"], 3) for r in rows
              if r["model"] in ("ridge_pooled", "ridge_per_class", "ridge_per_instrument")}
    inst = per_instrument_net(p, fc[champ["model"]], costs, dev).sort_values()

    summary = {
        "N": N, "luck_bar_annual": sr0 * np.sqrt(rows[0]["af"]),
        "champion": champ["model"], "champion_dev": champ["dev_sharpe"],
        "champion_ci": ci, "champion_dsr": champ["dsr"], "best_rule": best_rule["model"],
        "holdout": holdout, "pooling": pooled,
        "table": [{k: v for k, v in r.items() if k not in ("daily", "af")} for r in rows],
        "champion_by_instrument": inst.round(3).to_dict(),
        "costs": costs.round(6).reset_index().to_dict("records"),
        "data_hash": data_id, "code": episodes.code_commit(), "seconds": time.time() - t0,
    }
    os.makedirs("docs/results", exist_ok=True)
    with open("docs/results/zoo-2026-09-19.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=float)
    print(f"\nwrote docs/results/zoo-2026-09-19.json  ({time.time() - t0:.0f}s total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
