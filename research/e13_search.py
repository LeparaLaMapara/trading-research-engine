"""E13: every hourly intraday window on 7 FX majors, searched on 2014-2022, short list tested
once on the sealed 2023-2026 vault. Rule fixed in docs/programme/E13-hourly-window-search-prereg.md
(registered and pushed before this file existed).

The trading day runs 18:00 New York to 16:00 next day: 23 slot times, offsets 0..22. A rule
buys or sells one pair at slot e and exits at slot e+k (k in 1,2,3,4,6,8; e+k <= 22), so it never
crosses the rollover. Fills at the open of the hourly bar: buy at the ask, sell at the bid.

    python -m research.e13_search         # writes docs/results/E13-hourly-window-search.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from math import erf, sqrt

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from research import vault
from research.e11_fix import sha256
from research.e12_fomc import load_quotes

DATA = r"T:\making-money\features\intraday\h1"
OUT = "docs/results/E13-hourly-window-search.json"
NY = "America/New_York"
SYMS = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD")
HOLDS = (1, 2, 3, 4, 6, 8)
SLOTS = 23                                     # offsets 0..22 (22 is 16:00 New York)
COMMISSION_SIDE = 0.35e-4
MAX_SPREAD_FRAC = 5e-4
WEEKDAYS = (None, 0, 1, 2, 3, 4)               # None = every day
PRIORS = (0, 1, -1)                            # 0 none, 1 rose over 24 h, -1 fell
MIN_TRADES, MIN_MEAN, MIN_POS_YEARS = 200, 0.5e-4, 6
SHORTLIST, MAX_CORR = 10, 0.3
VAULT_YEARS_POS = 3
DAYS = ("2014-01-02", "2026-09-30")


def slot_times(days: pd.DatetimeIndex, shift_h: int = 0) -> np.ndarray:
    """UTC times (naive datetime64) of each slot for each closing day; NaT where the New York
    clock skips or repeats (daylight-saving changes)."""
    base = days.normalize() + pd.Timedelta(hours=16)
    out = np.empty((len(days), SLOTS), dtype="datetime64[ns]")
    for o in range(SLOTS):
        local = base - pd.Timedelta(hours=22 - o) - pd.Timedelta(hours=shift_h)
        idx = pd.DatetimeIndex(local).tz_localize(NY, ambiguous="NaT", nonexistent="NaT")
        out[:, o] = idx.tz_convert("UTC").tz_localize(None).to_numpy()
    return out


def quote_grid(q: pd.DataFrame, times: np.ndarray):
    idx = q.index.tz_convert("UTC").tz_localize(None) if q.index.tz is not None else q.index
    q = pd.DataFrame(q.to_numpy(), index=idx, columns=q.columns)
    flat = pd.DatetimeIndex(times.ravel())
    bid = q["bid"].reindex(flat).to_numpy().reshape(times.shape)
    ask = q["ask"].reindex(flat).to_numpy().reshape(times.shape)
    mid = (bid + ask) / 2
    bad = ~(ask > bid) | ((ask - bid) / mid > MAX_SPREAD_FRAC)
    bid, ask = np.where(bad, np.nan, bid), np.where(bad, np.nan, ask)
    return bid, ask, mid


def windows():
    return [(e, k) for k in HOLDS for e in range(SLOTS - k)]


def rule_id(sym, e, k, d, wd, pr) -> str:
    return f"{sym}:e{e}:k{k}:{'buy' if d > 0 else 'sell'}:wd{'all' if wd is None else wd}:p{pr}"


class Panel:
    """Per-instrument grids of fills, plus the filters, for every closing day."""

    def __init__(self, quotes: dict, days: pd.DatetimeIndex):
        self.days = days
        self.years = days.year.to_numpy()
        self.weekday = days.weekday.to_numpy()
        t, t24 = slot_times(days), slot_times(days, shift_h=24)
        self.g = {}
        for s, q in quotes.items():
            bid, ask, mid = quote_grid(q, t)
            _, _, mid24 = quote_grid(q, t24)
            self.g[s] = (bid, ask, mid, np.sign(np.log(mid / mid24)))

    def returns(self, sym, e, k, d, cost_mult=1.0) -> np.ndarray:
        bid, ask, mid, _ = self.g[sym]
        b0, a0, m0 = bid[:, e], ask[:, e], mid[:, e]
        b1, a1, m1 = bid[:, e + k], ask[:, e + k], mid[:, e + k]
        if cost_mult != 1.0:
            b0, a0 = m0 - cost_mult * (m0 - b0), m0 + cost_mult * (a0 - m0)
            b1, a1 = m1 - cost_mult * (m1 - b1), m1 + cost_mult * (a1 - m1)
        gross = np.log(b1 / a0) if d > 0 else np.log(b0 / a1)
        return gross - 2 * COMMISSION_SIDE * cost_mult

    def mask(self, sym, e, wd, pr) -> np.ndarray:
        m = np.ones(len(self.days), bool)
        if wd is not None:
            m &= self.weekday == wd
        if pr:
            m &= self.g[sym][3][:, e] == pr
        return m


def trade_stats(r: np.ndarray) -> dict:
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 2:
        return {"n": n, "mean_bps": 0.0, "t": 0.0}
    sd = r.std(ddof=1)
    return {"n": int(n), "mean_bps": round(float(r.mean()) * 1e4, 3),
            "t": round(float(r.mean() / sd * sqrt(n)) if sd > 0 else 0.0, 3)}


def p_one_sided(t: float) -> float:
    return 0.5 * (1 - erf(t / sqrt(2)))


def years_positive(r: np.ndarray, years: np.ndarray) -> tuple[int, int]:
    ok = ~np.isnan(r)
    ys = np.unique(years)
    pos = sum(1 for y in ys if np.nansum(r[(years == y) & ok]) > 0)
    return pos, len(ys)


def search(panel: Panel, in_room: np.ndarray, log=print):
    """Score every rule on the search-room days. Returns (all per-obs Sharpes, eligible list)."""
    yrs = panel.years[in_room]
    sharpes, eligible = [], []
    for s in SYMS:
        for e, k in windows():
            for d in (1, -1):
                base = panel.returns(s, e, k, d)[in_room]
                for wd in WEEKDAYS:
                    for pr in PRIORS:
                        r = np.where(panel.mask(s, e, wd, pr)[in_room], base, np.nan)
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
                        eligible.append({"id": rule_id(s, e, k, d, wd, pr), "sym": s, "e": e, "k": k,
                                         "d": d, "wd": wd, "pr": pr, "years_pos": pos,
                                         "t": float(mu / sd * sqrt(len(x))),
                                         "series": np.nan_to_num(r)})
        log(f"{s}: searched, {len(eligible)} eligible so far")
    return sharpes, eligible


def pick(eligible: list[dict]) -> list[dict]:
    keep = []
    for c in sorted(eligible, key=lambda c: -c["t"]):
        if all(abs(np.corrcoef(c["series"], k["series"])[0, 1]) <= MAX_CORR for k in keep):
            keep.append(c)
        if len(keep) == SHORTLIST:
            break
    return keep


def holm(ps: list[float], alpha: float = 0.05) -> list[bool]:
    order = np.argsort(ps)
    ok = [False] * len(ps)
    for rank, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - rank):
            ok[i] = True
        else:
            break
    return ok


def run(data: str = DATA, quotes: dict | None = None, log_path: str = vault.LOG,
        n_prior: int | None = None, log=print) -> dict:
    t0 = time.time()
    from_disk = quotes is None
    quotes = quotes if quotes is not None else {s: load_quotes(s, data) for s in SYMS}
    days = pd.bdate_range(*DAYS)
    panel = Panel(quotes, days)
    in_room = np.asarray(vault.search_mask(days))
    sharpes, eligible = search(panel, in_room, log)
    short = pick(eligible)
    listing = [{k: c[k] for k in ("id", "sym", "e", "k", "d", "wd", "pr", "years_pos")}
               | {"search_t": round(c["t"], 3)} for c in short]
    n_rules = len(sharpes)
    if n_prior is None:
        from research.programme import load, status
        n_prior = status(load(), check_git=False).n_tried - n_rules
    n_total = int(n_prior) + n_rules
    sr_std = float(np.std(sharpes)) or 1e-9

    results = []
    if short:
        in_vault = np.asarray(vault.open_once("E13", listing, days, log_path))
        vy = panel.years[in_vault]
        for c, row in zip(short, listing):
            m = panel.mask(c["sym"], c["e"], c["wd"], c["pr"])[in_vault]
            r = np.where(m, panel.returns(c["sym"], c["e"], c["k"], c["d"])[in_vault], np.nan)
            hi = np.where(m, panel.returns(c["sym"], c["e"], c["k"], c["d"], 1.5)[in_vault], np.nan)
            st, st_hi = trade_stats(r), trade_stats(hi)
            pos, ny = years_positive(r, vy)
            x = pd.Series(r[~np.isnan(r)])
            results.append(row | {"vault": st, "vault_1p5x": st_hi, "vault_years_pos": f"{pos}/{ny}",
                                  "p": p_one_sided(st["t"]),
                                  "dsr_at_N": round(float(deflated_sharpe_ratio(x, n_total, sr_std)), 4)
                                  if len(x) > 2 else 0.0,
                                  "_pos": pos})
        hol = holm([r["p"] for r in results])
        for r, h in zip(results, hol):
            r["criteria"] = {"1_holm": bool(h and r["vault"]["mean_bps"] > 0),
                             "2_positive_1p5x": bool(r["vault_1p5x"]["mean_bps"] > 0),
                             "3_years": bool(r.pop("_pos") >= VAULT_YEARS_POS)}
            r["pass"] = all(r["criteria"].values())
    passed = [r["id"] for r in results if r["pass"]]
    files = {s: {side: sha256(glob.glob(os.path.join(data, f"{s.lower()}-h1-{side}-*.csv"))[0])
                 for side in ("bid", "ask")} for s in SYMS} if from_disk else {}
    return {"experiment": "E13", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prereg": "docs/programme/E13-hourly-window-search-prereg.md",
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
    print(json.dumps({k: res[k] for k in ("rules_searched", "eligible", "forward_candidates",
                                          "verdict")}, indent=1))
    for r in res["shortlist"]:
        print(r["id"], "search t", r["search_t"], "| vault", r["vault"], r["vault_years_pos"],
              "pass" if r["pass"] else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
