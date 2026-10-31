"""E12: short the dollar on scheduled Fed decision days. Scores the rule fixed in
docs/programme/E12-fomc-day-dollar-prereg.md (registered and pushed before this file existed).

For each scheduled FOMC statement day D: at 16:00 New York on the previous weekday sell the
dollar against seven currencies, equal notional; close at 16:00 New York on D. Fills at the
open of the hourly bar starting then: buy at the ask, sell at the bid. Commission 0.35 bps a
side, and the broker's financing for the night held (three nights across a Wednesday).

    python -m research.e12_fomc           # writes docs/results/E12-fomc-day-dollar.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from learning import stats
from news import fomc
from research.e11_fix import sha256
from zoo import financing as FIN

DATA = r"T:\making-money\features\intraday\h1"
OUT = "docs/results/E12-fomc-day-dollar.json"
NY = "America/New_York"
COMMISSION_SIDE = 0.35e-4
#: (symbol, True when selling the dollar means BUYING the pair)
LEGS = (("EURUSD", True), ("GBPUSD", True), ("AUDUSD", True), ("NZDUSD", True),
        ("USDJPY", False), ("USDCHF", False), ("USDCAD", False))
DECIDE = ("2014-01-01", "2026-09-30")
HALVES = (("2014-01-01", "2019-12-31"), ("2020-01-01", "2026-09-30"))
N_NULL, TRIALS, EVENTS_PER_YEAR = 2000, 8, 8.0
MAX_SPREAD_FRAC = 5e-4                         # a 5 bps spread at 16:00 ET means bad data


def load_quotes(sym: str, data: str = DATA) -> pd.DataFrame:
    out = {}
    for side in ("bid", "ask"):
        hits = glob.glob(os.path.join(data, f"{sym.lower()}-h1-{side}-*.csv"))
        if len(hits) != 1:
            raise FileNotFoundError(f"need exactly one {sym} {side} file in {data}, found {hits}")
        df = pd.read_csv(hits[0], usecols=["timestamp", "open"])
        out[side] = pd.Series(df["open"].to_numpy(), index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))
    return pd.DataFrame(out).dropna()


def at_4pm(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return (dates.normalize() + pd.Timedelta(hours=16)).tz_localize(NY).tz_convert("UTC")


def prev_weekday(d: pd.Timestamp) -> pd.Timestamp:
    return d - pd.offsets.BDay(1)


def nights(entry_day: pd.Timestamp, spec: dict) -> int:
    """Nights of financing for the one rollover crossed (17:00 ET on entry_day): three when it is
    the broker's triple day (swapRollover3Days, 0 Sunday .. 6 Saturday; 3 = Wednesday, which
    pays for the weekend), else one. A Friday rollover is a single night."""
    triple = int(spec.get("swapRollover3Days", 3))
    return 3 if (entry_day.weekday() + 1) % 7 == triple else 1


def event_returns(entries: pd.DatetimeIndex, quotes: dict, swaps: dict,
                  cost_mult: float = 1.0) -> pd.DataFrame:
    """Net return per leg (columns) for each entry day (rows); NaN where a fill is missing."""
    exits = pd.DatetimeIndex([e + pd.offsets.BDay(1) for e in entries])
    t0, t1 = at_4pm(entries), at_4pm(exits)
    cols = {}
    for sym, buy in LEGS:
        q = quotes[sym]
        b0, a0 = q["bid"].reindex(t0).to_numpy(), q["ask"].reindex(t0).to_numpy()
        b1, a1 = q["bid"].reindex(t1).to_numpy(), q["ask"].reindex(t1).to_numpy()
        m0, m1 = (b0 + a0) / 2, (b1 + a1) / 2
        bad = ~(a0 > b0) | ~(a1 > b1) | ((a0 - b0) / m0 > MAX_SPREAD_FRAC) | ((a1 - b1) / m1 > MAX_SPREAD_FRAC)
        b0, a0 = m0 - cost_mult * (m0 - b0), m0 + cost_mult * (a0 - m0)
        b1, a1 = m1 - cost_mult * (m1 - b1), m1 + cost_mult * (a1 - m1)
        gross = np.log(b1 / a0) if buy else np.log(b0 / a1)
        long_rate, short_rate = FIN.annual_rates(swaps[sym], float(np.nanmedian(m0)))
        rate = long_rate if buy else short_rate
        fin = np.array([nights(e, swaps[sym]) for e in entries]) * rate / 365.0
        # Stressed costs scale financing that is PAID; financing received is never scaled up.
        r = gross - 2 * COMMISSION_SIDE * cost_mult + fin * (cost_mult if rate < 0 else 1.0)
        cols[sym] = np.where(bad, np.nan, r)
    return pd.DataFrame(cols, index=exits)


def summarise(r: pd.Series) -> dict:
    r = r.dropna()
    sd = r.std(ddof=1)
    return {"n_events": int(len(r)), "mean_bps": round(float(r.mean()) * 1e4, 3),
            "t": round(stats.t_stat(r), 3), "sharpe": round(stats.annual_sharpe(r, EVENTS_PER_YEAR), 3),
            "per_obs_sharpe": float(r.mean() / sd) if sd > 0 else 0.0}


def run(data: str = DATA, n_null: int = N_NULL, n_prior: int | None = None, seed: int = 12,
        dates: list[str] | None = None, swaps: dict | None = None, log=print) -> dict:
    t0 = time.time()
    swaps = swaps if swaps is not None else FIN.load()
    quotes = {s: load_quotes(s, data) for s, _ in LEGS}
    files = {}
    for s, _ in LEGS:
        files[s] = {side: sha256(glob.glob(os.path.join(data, f"{s.lower()}-h1-{side}-*.csv"))[0])
                    for side in ("bid", "ask")}
    days = pd.DatetimeIndex(pd.to_datetime(dates if dates is not None else fomc.load()))
    days = days[(days >= DECIDE[0]) & (days <= DECIDE[1])]
    entries = pd.DatetimeIndex([prev_weekday(d) for d in days])
    legs = event_returns(entries, quotes, swaps)
    book = legs.mean(axis=1, skipna=False)
    trials = [{"id": s, **summarise(legs[s])} for s in legs.columns] + [{"id": "book", **summarise(book)}]
    main = summarise(book)

    # Criterion 2: random non-FOMC weekdays with the same weekday mix.
    pool = pd.bdate_range(DECIDE[0], DECIDE[1])
    pool = pool[~pool.isin(days)]
    by_wd = {w: pool[pool.weekday == w] for w in range(5)}
    rng = np.random.default_rng(seed)
    want = days.weekday
    null_means = np.empty(n_null)
    all_null_days = [by_wd[w][rng.integers(0, len(by_wd[w]), size=n_null)] for w in want]
    draws = np.stack([np.asarray(x) for x in all_null_days], axis=1)       # (n_null, events)
    flat = pd.DatetimeIndex(draws.ravel())
    null_ret = event_returns(pd.DatetimeIndex([prev_weekday(d) for d in flat]), quotes, swaps)
    null_book = null_ret.mean(axis=1, skipna=False).to_numpy().reshape(draws.shape)
    null_means[:] = np.nanmean(null_book, axis=1)

    hi = event_returns(entries, quotes, swaps, cost_mult=1.5).mean(axis=1, skipna=False)
    halves = [summarise(book[(book.index >= a) & (book.index <= b)]) for a, b in HALVES]

    if n_prior is None:
        from research.programme import load, status
        n_prior = status(load(), check_git=False).n_tried - TRIALS
    n_total = int(n_prior) + TRIALS
    sr_std = float(np.std([t["per_obs_sharpe"] for t in trials])) or 1e-9
    dsr = deflated_sharpe_ratio(book.dropna().astype(float), n_total, sr_std)

    crit = {
        "1_mean_positive_t_ge_2": bool(main["mean_bps"] > 0 and main["t"] >= stats.T_BAR_PUBLISHED),
        "2_beats_null_p95": bool(main["mean_bps"] / 1e4 > float(np.nanpercentile(null_means, 95))),
        "3_positive_at_1p5x_costs": bool(summarise(hi)["mean_bps"] > 0),
        "4_both_halves_positive": bool(all(h["mean_bps"] > 0 for h in halves)),
    }
    passed = all(crit.values())
    verdict = ("PASS" if passed and dsr >= 0.5 else
               "PASS (screen only, deflated Sharpe < 0.5)" if passed else "FAIL")
    return {
        "experiment": "E12", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prereg": "docs/programme/E12-fomc-day-dollar-prereg.md", "deciding_sample": list(DECIDE),
        "events_in_sample": int(len(days)), "events_dropped": int(book.isna().sum()),
        "book": main, "book_1p5x_costs": summarise(hi),
        "halves": {f"{a[:4]}-{b[:4]}": h for (a, b), h in zip(HALVES, halves)},
        "null": {"draws": n_null, "mean_bps_p50": round(float(np.nanpercentile(null_means, 50)) * 1e4, 3),
                 "mean_bps_p95": round(float(np.nanpercentile(null_means, 95)) * 1e4, 3)},
        "criteria": crit, "n_total": n_total, "dsr_at_N": round(float(dsr), 4), "verdict": verdict,
        "trials": trials, "data": files, "seconds": round(time.time() - t0, 1),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    res = run(a.data)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({k: res[k] for k in ("book", "criteria", "dsr_at_N", "verdict")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
