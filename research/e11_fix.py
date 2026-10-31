"""E11: the dollar around the European currency fixes. Scores the rule fixed in
docs/programme/E11-fx-fix-reversal-prereg.md (registered and pushed before this file existed).

Each weekday, per instrument: own the dollar 02:00-08:15 New York time (into the ECB fix), own
the foreign currency 11:00-16:30 (after the London fix). Fills at the open of the 5-minute bar
starting at each boundary: buy at the ask, sell at the bid. Commission 0.35 bps a side.

    python -m research.e11_fix            # writes docs/results/E11-fx-fix-reversal.json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import time

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio
from learning import stats

DATA = r"T:\making-money\features\intraday\m5"
OUT = "docs/results/E11-fx-fix-reversal.json"
NY = "America/New_York"
COMMISSION_SIDE = 0.35e-4
MAX_SPREAD_PIPS, PIP = 5.0, 1e-4
BOOK = ("EURUSD", "GBPUSD")
INSTRUMENTS = ("EURUSD", "GBPUSD", "USDCHF")
PRE, POST = ("02:00", "08:15"), ("11:00", "16:30")
GRID = ("02:00", "16:30")                    # the null draws start times inside this span
DECIDE = ("2020-01-01", "2026-09-30")
REPLICATE = ("2015-01-01", "2019-12-31")
N_NULL, TRIALS = 2000, 10


def csv_path(sym: str, side: str, data: str = DATA) -> str:
    hits = glob.glob(os.path.join(data, f"{sym.lower()}-m5-{side}-*.csv"))
    if len(hits) != 1:
        raise FileNotFoundError(f"need exactly one {sym} {side} file in {data}, found {hits}")
    return hits[0]


def load_quotes(sym: str, data: str = DATA) -> pd.DataFrame:
    """bid and ask OPEN of every 5-minute bar, indexed by bar open time in UTC."""
    out = {}
    for side in ("bid", "ask"):
        df = pd.read_csv(csv_path(sym, side, data), usecols=["timestamp", "open"])
        out[side] = pd.Series(df["open"].to_numpy(), index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))
    return pd.DataFrame(out).dropna()


def grid(days: pd.DatetimeIndex, start: str, end: str) -> pd.DataFrame:
    """UTC timestamps of every 5-minute step from start to end (New York clock) on each day."""
    steps = pd.timedelta_range(pd.Timedelta(start + ":00"), pd.Timedelta(end + ":00"), freq="5min")
    local = [(d + s) for d in days for s in steps]
    idx = pd.DatetimeIndex(local).tz_localize(NY, ambiguous="NaT", nonexistent="NaT")
    utc = idx.tz_convert("UTC").tz_localize(None).to_numpy()     # naive UTC, NaT kept
    return pd.DataFrame(utc.reshape(len(days), len(steps)),
                        index=days, columns=[str(s)[-8:-3] for s in steps])


def day_matrix(q: pd.DataFrame, days: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """bid and ask on the GRID for every day: arrays (days x steps), NaN where missing or bad."""
    g = grid(days, *GRID)
    flat = pd.DatetimeIndex(g.to_numpy().ravel()).tz_localize("UTC")
    bid = q["bid"].reindex(flat).to_numpy().reshape(g.shape)
    ask = q["ask"].reindex(flat).to_numpy().reshape(g.shape)
    bad = ~(ask > bid) | ((ask - bid) > MAX_SPREAD_PIPS * PIP)
    bid, ask = np.where(bad, np.nan, bid), np.where(bad, np.nan, ask)
    return bid, ask, list(g.columns)


def leg(bid: np.ndarray, ask: np.ndarray, i: np.ndarray, j: np.ndarray, long_quote: bool,
        cost_mult: float = 1.0) -> np.ndarray:
    """Log return of one leg opened at column i and closed at column j, per row.

    long_quote: buy the quoted pair at i (ask) and sell at j (bid); else the reverse. Costs are
    scaled by widening the spread around the mid and multiplying commission."""
    rows = np.arange(bid.shape[0])
    b0, a0, b1, a1 = bid[rows, i], ask[rows, i], bid[rows, j], ask[rows, j]
    if cost_mult != 1.0:
        m0, m1 = (b0 + a0) / 2, (b1 + a1) / 2
        b0, a0 = m0 - cost_mult * (m0 - b0), m0 + cost_mult * (a0 - m0)
        b1, a1 = m1 - cost_mult * (m1 - b1), m1 + cost_mult * (a1 - m1)
    gross = np.log(b1 / a0) if long_quote else np.log(b0 / a1)
    return gross - 2 * COMMISSION_SIDE * cost_mult


def instrument_days(sym: str, bid, ask, cols, cost_mult: float = 1.0) -> dict[str, np.ndarray]:
    """Daily net returns for the pre-ECB leg, the post-London leg and both. A dollar-quoted pair
    (USDCHF) owns the dollar by BUYING it, a foreign-quoted pair (EURUSD) by SELLING."""
    usd_base = sym.startswith("USD")
    c = {k: cols.index(k) for k in (*PRE, *POST)}
    n = bid.shape[0]
    pre = leg(bid, ask, np.full(n, c[PRE[0]]), np.full(n, c[PRE[1]]), long_quote=usd_base,
              cost_mult=cost_mult)
    post = leg(bid, ask, np.full(n, c[POST[0]]), np.full(n, c[POST[1]]), long_quote=not usd_base,
               cost_mult=cost_mult)
    return {"pre": pre, "post": post, "both": pre + post}


def null_draws(bid, ask, cols, sym: str, n_draws: int, seed: int) -> np.ndarray:
    """Mean net daily return of `n_draws` random-timing versions (same leg lengths, order and
    directions, random starts on the 5-minute grid, legs not overlapping). Shape (n_draws, days)."""
    usd_base = sym.startswith("USD")
    la = cols.index(PRE[1]) - cols.index(PRE[0])
    lb = cols.index(POST[1]) - cols.index(POST[0])
    last = len(cols) - 1
    rng = np.random.default_rng(seed)
    n = bid.shape[0]
    sa = rng.integers(0, last - la - lb + 1, size=(n_draws, n))
    # sb uniform on [sa + la, last - lb]
    span = (last - lb) - (sa + la) + 1
    sb = sa + la + (rng.random((n_draws, n)) * span).astype(int)
    out = np.empty((n_draws, n))
    for k in range(n_draws):
        out[k] = (leg(bid, ask, sa[k], sa[k] + la, long_quote=usd_base)
                  + leg(bid, ask, sb[k], sb[k] + lb, long_quote=not usd_base))
    return out


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def summarise(r: pd.Series) -> dict:
    r = r.dropna()
    years = (r.index[-1] - r.index[0]).days / 365.25 if len(r) > 1 else 0.0
    bpy = len(r) / years if years else 252.0
    return {"n_days": int(len(r)), "mean_bps": round(float(r.mean()) * 1e4, 3),
            "sharpe": round(stats.annual_sharpe(r, bpy), 3), "t": round(stats.t_stat(r), 3),
            "per_obs_sharpe": float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0,
            "bars_per_year": round(bpy, 1)}


def run(data: str = DATA, n_null: int = N_NULL, n_prior: int | None = None, log=print) -> dict:
    t0 = time.time()
    days = pd.bdate_range("2014-01-02", DECIDE[1])
    mats, files = {}, {}
    for sym in INSTRUMENTS:
        q = load_quotes(sym, data)
        mats[sym] = day_matrix(q, days)
        files[sym] = {s: {"file": os.path.basename(csv_path(sym, s, data)),
                          "sha256": sha256(csv_path(sym, s, data))} for s in ("bid", "ask")}
        log(f"{sym}: {len(q):,} quotes")

    series, trials = {}, []
    for sym in INSTRUMENTS:
        bid, ask, cols = mats[sym]
        for k, v in instrument_days(sym, bid, ask, cols).items():
            series[f"{sym}:{k}"] = pd.Series(v, index=days)
    book = pd.concat([series[f"{s}:both"] for s in BOOK], axis=1)
    series["book"] = book.mean(axis=1, skipna=False)

    def window(r, span):
        return r[(r.index >= span[0]) & (r.index <= span[1])].dropna()

    dropped = {s: int(np.isnan(series[f"{s}:both"].loc[DECIDE[0]:DECIDE[1]]).sum()) for s in INSTRUMENTS}
    for tid, r in series.items():
        trials.append({"id": tid, **summarise(window(r, DECIDE))})

    # Criterion 2: random-timing null on the book.
    nulls = []
    for i, s in enumerate(BOOK):
        bid, ask, cols = mats[s]
        nulls.append(null_draws(bid, ask, cols, s, n_null, seed=11 + i))
    null_book = (nulls[0] + nulls[1]) / 2           # NaN if either leg is missing, like the book
    mask = (days >= DECIDE[0]) & (days <= DECIDE[1]) & series["book"].notna().to_numpy()
    nb = null_book[:, mask]
    bpy_book = summarise(window(series["book"], DECIDE))["bars_per_year"]
    null_sh = np.array([np.nanmean(x) / np.nanstd(x, ddof=1) * np.sqrt(bpy_book) for x in nb])

    # Criterion 3: 1.5x costs.
    hi = [pd.Series(instrument_days(s, *mats[s], cost_mult=1.5)["both"], index=days) for s in BOOK]
    book_hi = window(pd.concat(hi, axis=1).mean(axis=1, skipna=False), DECIDE)

    dec = window(series["book"], DECIDE)
    by_year = dec.groupby(dec.index.year).sum()
    main = summarise(dec)

    if n_prior is None:
        from research.programme import load, status
        reg = load()
        n_prior = status(reg, check_git=False).n_tried - TRIALS   # register already counts E11
    n_total = int(n_prior) + TRIALS
    sr_std = float(np.std([t["per_obs_sharpe"] for t in trials])) or 1e-9
    dsr = deflated_sharpe_ratio(dec.astype(float), n_total, sr_std)

    crit = {
        "1_sharpe_positive_t_ge_2": bool(main["sharpe"] > 0 and main["t"] >= stats.T_BAR_PUBLISHED),
        "2_beats_null_p95": bool(main["sharpe"] > float(np.nanpercentile(null_sh, 95))),
        "3_positive_at_1p5x_costs": bool(summarise(book_hi)["sharpe"] > 0),
        "4_positive_5_of_7_years": bool(int((by_year > 0).sum()) >= 5),
    }
    passed = all(crit.values())
    verdict = ("PASS" if passed and dsr >= 0.5 else
               "PASS (screen only, deflated Sharpe < 0.5)" if passed else "FAIL")
    rep = summarise(window(series["book"], REPLICATE))
    return {
        "experiment": "E11", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prereg": "docs/programme/E11-fx-fix-reversal-prereg.md",
        "deciding_sample": list(DECIDE), "replication_sample": list(REPLICATE),
        "book": main, "book_1p5x_costs": summarise(book_hi),
        "by_year_net_pct": {int(y): round(float(v) * 100, 2) for y, v in by_year.items()},
        "null": {"draws": n_null, "sharpe_p50": round(float(np.nanpercentile(null_sh, 50)), 3),
                 "sharpe_p95": round(float(np.nanpercentile(null_sh, 95)), 3)},
        "replication_2015_2019": rep,
        "criteria": crit, "n_total": n_total, "dsr_at_N": round(float(dsr), 4),
        "verdict": verdict, "trials": trials, "dropped_days": dropped, "data": files,
        "seconds": round(time.time() - t0, 1),
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
