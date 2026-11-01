"""E15: every hourly intraday window on Bitcoin and Ethereum at the broker's measured spread,
searched on 2017-2022, short list tested once on the 2023-2026 vault. Rule fixed in
docs/programme/E15-crypto-hourly-search-prereg.md (registered and pushed before this file existed).

    python -m research.e15_crypto         # writes docs/results/E15-crypto-hourly-search.json
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from research import vault
from research.e11_fix import sha256
from research.e13_search import (Panel, holm, p_one_sided, pick, search, trade_stats,
                                 years_positive)

DATA = r"T:\making-money\features\intraday\crypto_h1"
OUT = "docs/results/E15-crypto-hourly-search.json"
#: broker symbol -> (Binance file stem, round-trip spread: p95 of data/telemetry.db ticks)
SYMS = {"BTCUSD": ("btcusdt", 4.82e-4), "ETHUSD": ("ethusdt", 12.42e-4)}
DAYS = ("2017-08-18", "2026-09-30")
WEEKDAYS = (None, 0, 1, 2, 3, 4, 5, 6)
MIN_TRADES, MIN_MEAN, MIN_POS_YEARS = 200, 1.0e-4, 4
VAULT_YEARS_POS = 3
MAX_SPREAD = 20e-4


def path(stem: str, data: str) -> str:
    return os.path.join(data, f"{stem}-h1.csv")


def load_quotes(sym: str, data: str = DATA) -> pd.DataFrame:
    stem, spread = SYMS[sym]
    df = pd.read_csv(path(stem, data), usecols=["timestamp", "open"])
    mid = pd.Series(df["open"].to_numpy(float), index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))
    return pd.DataFrame({"bid": mid * (1 - spread / 2), "ask": mid * (1 + spread / 2)})


def run(data: str = DATA, quotes: dict | None = None, log_path: str = vault.LOG,
        n_prior: int | None = None, log=print) -> dict:
    t0 = time.time()
    from_disk = quotes is None
    quotes = quotes if quotes is not None else {s: load_quotes(s, data) for s in SYMS}
    days = pd.date_range(*DAYS, freq="D")
    panel = Panel(quotes, days, max_spread=MAX_SPREAD)
    room = np.asarray(vault.search_mask(days))
    sharpes, eligible = search(panel, room, log, syms=tuple(SYMS), weekdays=WEEKDAYS,
                               min_trades=MIN_TRADES, min_mean=MIN_MEAN, min_pos_years=MIN_POS_YEARS)
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
        vm = np.asarray(vault.open_once("E15", listing, days, log_path))
        vy = panel.years[vm]
        for c, row in zip(short, listing):
            m = panel.mask(c["sym"], c["e"], c["wd"], c["pr"])[vm]
            r = np.where(m, panel.returns(c["sym"], c["e"], c["k"], c["d"])[vm], np.nan)
            hi = np.where(m, panel.returns(c["sym"], c["e"], c["k"], c["d"], 1.5)[vm], np.nan)
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
    files = {s: sha256(path(stem, data)) for s, (stem, _) in SYMS.items()} if from_disk else {}
    return {"experiment": "E15", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prereg": "docs/programme/E15-crypto-hourly-search-prereg.md",
            "spread_round_trip_bps": {s: v * 1e4 for s, (_, v) in SYMS.items()},
            "search_room": [DAYS[0], vault.SEARCH[1]], "vault": list(vault.VAULT),
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
              "PASS" if r["pass"] else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
