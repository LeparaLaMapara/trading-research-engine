"""FX carry, per docs/results/carry-preregistration-2026-09-19.md.

Run:  python -m scripts.carry              # development phase
      python -m scripts.carry --holdout    # the one-time holdout read for the champion
"""
from __future__ import annotations

import argparse
import glob
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
from scripts.train_zoo import (DB, DEV_YEARS, EMBARGO, HOLDOUT_START, ann_factor,
                               block_bootstrap_sharpe, honest_n, max_dd, scaled, sharpe)
from zoo import models as Z
from zoo.panel import build_panel
from zoo.portfolio import cost_table, portfolio_returns

RATES_DIR = os.path.join(os.environ.get("ARTIFACT_ROOT", r"T:\making-money"), "features", "rates")
CCY = {"USD": "US", "EUR": "EZ", "GBP": "GB", "JPY": "JP", "AUD": "AU", "NZD": "NZ",
       "CAD": "CA", "CHF": "CH", "NOK": "NO", "SEK": "SE", "PLN": "PL", "MXN": "MX", "ZAR": "ZA"}
PROGRAMME = "carry-2026-09-19"
PUBLICATION_LAG_MONTHS = 2


def load_rates() -> pd.DataFrame:
    """Daily point-in-time rate table (percent), one column per currency."""
    cols = {}
    for ccy, cc in CCY.items():
        path = os.path.join(RATES_DIR, f"IR3TIB01{cc}M156N.csv")
        s = pd.read_csv(path)
        s.columns = ["month", "rate"]
        s["rate"] = pd.to_numeric(s["rate"], errors="coerce")
        s = s.dropna()
        # Month M's value becomes usable on the first day of month M+2.
        s["usable"] = pd.to_datetime(s["month"]) + pd.DateOffset(months=PUBLICATION_LAG_MONTHS)
        cols[ccy] = s.set_index("usable")["rate"]
    df = pd.DataFrame(cols).sort_index()
    days = pd.date_range(df.index.min(), pd.Timestamp.today().normalize(), freq="D")
    return df.reindex(days).ffill()


def differential(p: pd.DataFrame, rates: pd.DataFrame) -> pd.Series:
    """Annual % interest differential base minus quote per row; NaN where not covered."""
    out = pd.Series(np.nan, index=p.index)
    for sym, idx in p.groupby("symbol").groups.items():
        base, quote = sym[:3], sym[3:6]
        if len(sym) != 6 or base not in CCY or quote not in CCY:
            continue
        d = p.loc[idx, "date"]
        out.loc[idx] = (rates[base].reindex(d).to_numpy() - rates[quote].reindex(d).to_numpy())
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args()
    t0 = time.time()

    rates = load_rates()
    full = build_panel(extended_universe())
    full["diff"] = differential(full, rates)
    p = full[full["diff"].notna()].reset_index(drop=True)
    costs = cost_table(p)
    income = p["diff"] / 100.0 / 260.0
    print(f"carry universe: {p['symbol'].nunique()} FX pairs, {len(p):,} rows")

    ann_vol = p["sigma"] * np.sqrt(260) * 100.0
    raw = {
        "fx_zero_carry_long": lambda m: np.ones(m.sum()),
        "carry_ts": lambda m: (p.loc[m, "diff"] / ann_vol[m]).to_numpy(),
        "carry_xs": lambda m: ((p.loc[m].groupby("date")["diff"].rank(pct=True) - 0.5) * 2)
        .to_numpy(),
        "ewmac_fx_withcarry": lambda m: Z.ewmac(p, m, m),
    }
    fc = {k: pd.Series(np.nan, index=p.index) for k in raw}
    for y in DEV_YEARS + ["holdout"]:
        if y == "holdout":
            start, end = HOLDOUT_START, p["date"].max() + pd.Timedelta(days=1)
        else:
            start = pd.Timestamp(f"{y}-01-01")
            end = min(pd.Timestamp(f"{y + 1}-01-01"), HOLDOUT_START)
        tr = p["date"] < (start - EMBARGO)
        te = (p["date"] >= start) & (p["date"] < end)
        for k, fn in raw.items():
            if k == "ewmac_fx_withcarry":
                raw_te, raw_tr = Z.ewmac(p, tr, te), Z.ewmac(p, tr, tr)
            else:
                raw_te, raw_tr = fn(te), fn(tr)
            if k == "fx_zero_carry_long":
                raw_tr = np.ones(1)
            fc[k][te] = scaled(np.asarray(raw_te, float), np.asarray(raw_tr, float))
    fc["carry_trend"] = ((fc["carry_ts"] + fc["ewmac_fx_withcarry"]) / 2.0)
    # Rescale the blend with prior-years magnitude only, as the zoo's ensembles do.
    yr = p["date"].dt.year.where(p["date"] < HOLDOUT_START, 9999)
    blend = fc["carry_trend"].copy()
    for y in sorted(yr.unique()):
        prior = fc["carry_trend"][(yr < y) & fc["carry_trend"].notna()]
        k = 1.0 / prior.abs().mean() if len(prior) else 1.0
        blend[yr == y] = (fc["carry_trend"][yr == y] * k).clip(-2, 2)
    fc["carry_trend"] = blend

    dev = (p["date"] >= pd.Timestamp("2017-01-01")) & (p["date"] < HOLDOUT_START)
    conn = sqlite3.connect(DB)
    rows = []
    for k, f in fc.items():
        d = portfolio_returns(p, f, costs, dev, income=income)
        af = ann_factor(d)
        yearly = {int(y): round(sharpe(g["net"], af), 3) for y, g in d.groupby(d.index.year)}
        price_only = portfolio_returns(p, f, costs, dev)
        rows.append({"model": k, "dev_sharpe": sharpe(d["net"], af),
                     "price_only_sharpe": sharpe(price_only["net"], af),
                     "per_obs": wf.per_obs_sharpe(d["net"]), "yearly": yearly,
                     "years_positive": sum(v > 0 for v in yearly.values()),
                     "max_dd": max_dd(d["net"]), "af": af, "daily": d})

    conn.execute("DELETE FROM trials WHERE variant LIKE ?", (f"{PROGRAMME}:%",))
    now = time.time()
    for r in rows:
        conn.execute("INSERT INTO trials (variant, strategy_kind, symbol, period, stage, "
                     "per_obs_sharpe, n_bars, created_ts) VALUES (?,?,?,?,?,?,?,?)",
                     (f"{PROGRAMME}:{r['model']}", r["model"], "FX31", "D1", "carry_dev",
                      r["per_obs"], len(r["daily"]), now))
    conn.commit()
    N = honest_n(conn)
    zoo_spread = [x[0] for x in conn.execute(
        "SELECT per_obs_sharpe FROM trials WHERE stage IN ('zoo_dev','carry_dev')")]
    spread = float(np.std(zoo_spread)) if len(zoo_spread) > 2 else 0.03
    for r in rows:
        r["dsr"] = wf.deflated_sharpe_ratio(r["daily"]["net"], N, spread)
    rows.sort(key=lambda r: r["dev_sharpe"], reverse=True)

    print(f"\nhonest N = {N}; luck bar (annualised) = "
          f"{wf.expected_max_sharpe(spread, N) * np.sqrt(rows[0]['af']):.3f}\n")
    print(f"{'model':<22}{'net+carry':>10}{'price only':>11}{'yrs+':>6}{'maxDD':>8}{'DSR':>7}")
    for r in rows:
        print(f"{r['model']:<22}{r['dev_sharpe']:>10.3f}{r['price_only_sharpe']:>11.3f}"
              f"{r['years_positive']:>4}/8{r['max_dd']:>8.2f}{r['dsr']:>7.3f}   {r['yearly']}")

    champ = next(r for r in rows if r["model"] != "fx_zero_carry_long")
    ci = block_bootstrap_sharpe(champ["daily"]["net"].to_numpy(), champ["af"])
    print(f"\nchampion {champ['model']}: dev {champ['dev_sharpe']:.3f}, CI [{ci[0]:.2f}, "
          f"{ci[1]:.2f}], DSR {champ['dsr']:.3f}")
    hold = {}
    if a.holdout:
        hm = p["date"] >= HOLDOUT_START
        for k in dict.fromkeys([champ["model"], "fx_zero_carry_long"]):
            d = portfolio_returns(p, fc[k], costs, hm, income=income)
            hold[k] = sharpe(d["net"], ann_factor(d))
            print(f"  HOLDOUT {k:<22} {hold[k]:.3f}  ({len(d)} days)")

    out = {"N": N, "champion": champ["model"], "ci": ci, "holdout": hold,
           "table": [{k: v for k, v in r.items() if k not in ("daily", "af")} for r in rows],
           "pairs": sorted(p["symbol"].unique())}
    with open("docs/results/carry-2026-09-19.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
