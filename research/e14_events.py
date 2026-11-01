"""E14: event days (US jobs, US inflation, month end, month start) on 7 FX majors, searched on
2014-2022, short list tested once on the 2023-2026 vault. Rule fixed in
docs/programme/E14-event-day-search-prereg.md (registered and pushed before this file existed).

    python -m research.e14_events         # writes docs/results/E14-event-day-search.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from math import sqrt

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from news import releases
from research import vault
from research.e11_fix import sha256
from research.e12_fomc import load_quotes
from research.e13_search import (DATA, DAYS, SYMS, Panel, holm, p_one_sided, pick, trade_stats,
                                 windows, years_positive)

OUT = "docs/results/E14-event-day-search.json"
SLOT_0800, SLOT_1600 = 14, 22
REACT_END = (15, 16)                           # 09:00 and 10:00 New York
MIN_TRADES, MIN_MEAN, MIN_POS_YEARS = 80, 1.0e-4, 6
VAULT_YEARS_POS = 3


def event_masks(days: pd.DatetimeIndex, nfp: list[str], cpi: list[str]) -> dict:
    s = pd.Series(days, index=days)
    month = days.to_period("M")
    last = s.groupby(month).transform("max").to_numpy() == days.to_numpy()
    first = s.groupby(month).transform("min").to_numpy() == days.to_numpy()
    return {"NFP": days.isin(pd.to_datetime(nfp)), "CPI": days.isin(pd.to_datetime(cpi)),
            "MEND": last, "MSTART": first}


def reaction_returns(panel: Panel, sym: str, r: int, x: int, mode: int, cost_mult=1.0):
    mid = panel.g[sym][2]
    sign = np.sign(np.log(mid[:, r] / mid[:, SLOT_0800])) * mode
    buy = panel.returns(sym, r, x - r, 1, cost_mult)
    sell = panel.returns(sym, r, x - r, -1, cost_mult)
    out = np.where(sign > 0, buy, np.where(sign < 0, sell, np.nan))
    return np.where(np.isnan(sign), np.nan, out)


def rule_space(panel: Panel, masks: dict):
    """Yields (spec, fn(cost_mult) -> net return per day, NaN when no trade)."""
    for ev in ("NFP", "CPI"):
        m = masks[ev]
        for r in REACT_END:
            for x in range(r + 1, SLOT_1600 + 1):
                for mode, name in ((1, "follow"), (-1, "fade")):
                    for sym in SYMS + ("BASKET",):
                        spec = {"id": f"A:{ev}:r{r}:x{x}:{name}:{sym}", "kind": "reaction", "event": ev,
                                "sym": sym, "r": r, "x": x, "mode": mode}

                        def fn(c=1.0, sym=sym, r=r, x=x, mode=mode, m=m):
                            if sym == "BASKET":
                                v = np.mean([reaction_returns(panel, s, r, x, mode, c) for s in SYMS], axis=0)
                            else:
                                v = reaction_returns(panel, sym, r, x, mode, c)
                            return np.where(m, v, np.nan)
                        yield spec, fn
    for ev in ("NFP", "CPI", "MEND", "MSTART"):
        m = masks[ev]
        for sym in SYMS:
            for e, k in windows():
                for d in (1, -1):
                    spec = {"id": f"B:{ev}:{sym}:e{e}:k{k}:{'buy' if d > 0 else 'sell'}", "kind": "clock",
                            "event": ev, "sym": sym, "e": e, "k": k, "d": d}

                    def fn(c=1.0, sym=sym, e=e, k=k, d=d, m=m):
                        return np.where(m, panel.returns(sym, e, k, d, c), np.nan)
                    yield spec, fn


def run(data: str = DATA, quotes: dict | None = None, nfp=None, cpi=None,
        log_path: str = vault.LOG, n_prior: int | None = None, log=print) -> dict:
    t0 = time.time()
    from_disk = quotes is None
    quotes = quotes if quotes is not None else {s: load_quotes(s, data) for s in SYMS}
    nfp = nfp if nfp is not None else releases.load("NFP")
    cpi = cpi if cpi is not None else releases.load("CPI")
    days = pd.bdate_range(*DAYS)
    panel = Panel(quotes, days)
    masks = event_masks(days, nfp, cpi)
    room = np.asarray(vault.search_mask(days))
    yrs = panel.years[room]

    sharpes, eligible, fns = [], [], {}
    for spec, fn in rule_space(panel, masks):
        r = fn()[room]
        x = r[~np.isnan(r)]
        if len(x) < 2:
            sharpes.append(0.0)
            continue
        mu, sd = x.mean(), x.std(ddof=1)
        sharpes.append(float(mu / sd) if sd > 0 else 0.0)
        if len(x) < MIN_TRADES or mu < MIN_MEAN:
            continue
        pos, _ = years_positive(r, yrs)
        if pos < MIN_POS_YEARS:
            continue
        eligible.append(spec | {"years_pos": pos, "t": float(mu / sd * sqrt(len(x))),
                                "series": np.nan_to_num(r)})
        fns[spec["id"]] = fn
    log(f"searched {len(sharpes)} rules, {len(eligible)} eligible")
    short = pick(eligible)
    listing = [{k: v for k, v in c.items() if k not in ("series", "t")} | {"search_t": round(c["t"], 3)}
               for c in short]
    n_rules = len(sharpes)
    if n_prior is None:
        from research.programme import load, status
        n_prior = status(load(), check_git=False).n_tried - n_rules
    n_total = int(n_prior) + n_rules
    sr_std = float(np.std(sharpes)) or 1e-9

    results = []
    if short:
        vm = np.asarray(vault.open_once("E14", listing, days, log_path))
        vy = panel.years[vm]
        for row in listing:
            fn = fns[row["id"]]
            r, hi = fn()[vm], fn(1.5)[vm]
            st, st_hi = trade_stats(r), trade_stats(hi)
            pos, ny = years_positive(r, vy)
            x = pd.Series(r[~np.isnan(r)])
            results.append(row | {"vault": st, "vault_1p5x": st_hi, "vault_years_pos": f"{pos}/{ny}",
                                  "p": p_one_sided(st["t"]), "_pos": pos,
                                  "dsr_at_N": round(float(deflated_sharpe_ratio(x, n_total, sr_std)), 4)
                                  if len(x) > 2 else 0.0})
        for r, h in zip(results, holm([r["p"] for r in results])):
            r["criteria"] = {"1_holm": bool(h and r["vault"]["mean_bps"] > 0),
                             "2_positive_1p5x": bool(r["vault_1p5x"]["mean_bps"] > 0),
                             "3_years": bool(r.pop("_pos") >= VAULT_YEARS_POS)}
            r["pass"] = all(r["criteria"].values())
    passed = [r["id"] for r in results if r["pass"]]
    files = {s: {side: sha256(glob.glob(os.path.join(data, f"{s.lower()}-h1-{side}-*.csv"))[0])
                 for side in ("bid", "ask")} for s in SYMS} if from_disk else {}
    return {"experiment": "E14", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prereg": "docs/programme/E14-event-day-search-prereg.md",
            "events": {k: int(v.sum()) for k, v in masks.items()},
            "search_room": list(vault.SEARCH), "vault": list(vault.VAULT),
            "rules_searched": n_rules, "eligible": len(eligible), "shortlist": results,
            "forward_candidates": passed, "n_total": n_total,
            "verdict": "PASS" if passed else "FAIL", "data": files,
            "seconds": round(time.time() - t0, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    res = run(a.data)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({k: res[k] for k in ("events", "rules_searched", "eligible",
                                          "forward_candidates", "verdict")}, indent=1))
    for r in res["shortlist"]:
        print(r["id"], "search t", r["search_t"], "| vault", r["vault"], r["vault_years_pos"],
              "PASS" if r["pass"] else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
