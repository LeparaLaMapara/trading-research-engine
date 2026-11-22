"""Agenda item 1 data check: JSE ETF series, pre-inception proxies, SA cash rate.

DATA QUALITY ONLY. Nothing here computes or prints a mean return, CAGR, Sharpe, drawdown or any
rule signal: only dates, counts, gaps, bad prints, dividend adjustment checks, implied dividend
yields, and proxy-vs-ETF dispersion (correlation, tracking error) on overlaps BEFORE
scripts.train_zoo.HOLDOUT_START. 0 trials.

Sources
* Yahoo Finance chart API (query2.finance.yahoo.com/v8/finance/chart), daily bars with
  dividends and splits, prices in ZAc for .JO. Raw JSON cached under
  $ARTIFACT_ROOT/research-loop/etf-data-2026-11-22/ with a sha256 per file.
* FRED fredgraph.csv: IR3TIB01ZAM156N (SA 3-month interbank, monthly, % p.a.) as the cash leg;
  IRLTLT01ZAM156N (SA long-term government bond yield, monthly) for a MODELLED bond series.

Yahoo's JSE dividend record is incomplete (none before 2013, gaps, amounts in ZAR instead of ZAc
from 2024 for some funds; added 2026-11-22 after the first run). The rebuilt total return is
only trusted for years with a complete record; see years_with_bars_but_no_dividend,
years_below_usual_count, suspect_unit_switch_events. The later date of a duplicate pair is
ASSUMED to be the ex-date (UNVERIFIED; it can move a dividend across a month-end).

Synthetic bond (a model, not data): r_m = y_{m-1}/1200 - D * (y_m - y_{m-1})/100, D = 7.0
(ASSUMED modified duration of the SA all-bond index; checked only by tracking below).

Run: PYTHONPATH=. ARTIFACT_ROOT=/mnt/t/making-money nice python lab/etf/data_check.py
"""
import hashlib
import io
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from scripts.train_zoo import HOLDOUT_START

TODAY = "2026-11-22"
ROOT = os.path.join(os.environ.get("ARTIFACT_ROOT", "/mnt/t/making-money"),
                    "research-loop", f"etf-data-{TODAY}")
OUT = f"docs/results/etf-data-check-{TODAY}.json"
UA = {"User-Agent": "Mozilla/5.0"}
D_BOND = 7.0

# role: target ETF (what would be traded) or proxy (pre-inception history)
YAHOO = {
    "STX40.JO": ("SA equity", "target"),
    "STXWDM.JO": ("global equity", "target"),
    "STX500.JO": ("US equity", "target"),
    "STXGOV.JO": ("SA bonds", "target"),
    "STXPRO.JO": ("SA property", "target"),
    "GLD.JO": ("gold", "target"),
    "SYGWD.JO": ("global equity", "proxy"),
    "CSPROP.JO": ("SA property", "proxy"),
    "ETFBND.JO": ("SA bonds", "proxy"),
    "^J200.JO": ("SA equity", "proxy (price index)"),
    "URTH": ("global equity", "proxy (USD)"),
    "USDZAR=X": ("fx", "converter"),
}
FRED = ["IR3TIB01ZAM156N", "IRLTLT01ZAM156N"]
# proxy -> target pairs for tracking (monthly, pre-holdout overlap)
PAIRS = [("SYGWD.JO", "STXWDM.JO"), ("CSPROP.JO", "STXPRO.JO"), ("ETFBND.JO", "STXGOV.JO"),
         ("SYNTH_BOND", "STXGOV.JO"), ("SYNTH_BOND", "ETFBND.JO"), ("^J200.JO", "STX40.JO"),
         ("URTH_ZAR", "STXWDM.JO"), ("URTH_ZAR", "SYGWD.JO")]
# candidate 5-class sets: class -> series
SETS = {
    "A_targets_only": {"SA equity": "STX40.JO", "global equity": "STXWDM.JO",
                       "SA bonds": "STXGOV.JO", "SA property": "STXPRO.JO", "gold": "GLD.JO"},
    "B_real_zar_proxies": {"SA equity": "STX40.JO", "global equity": "SYGWD.JO",
                           "SA bonds": "ETFBND.JO", "SA property": "CSPROP.JO", "gold": "GLD.JO"},
    "C_synthetic_bond": {"SA equity": "STX40.JO", "global equity": "SYGWD.JO",
                         "SA bonds": "SYNTH_BOND", "SA property": "CSPROP.JO", "gold": "GLD.JO"},
}


def _epoch(d):
    return int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp())


def fetch(url, name):
    os.makedirs(ROOT, exist_ok=True)
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        for attempt in range(4):
            try:
                r = requests.get(url, headers=UA, timeout=120)
                r.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(10)
        with open(path, "wb") as f:
            f.write(r.content)
        time.sleep(1.5)
    raw = open(path, "rb").read()
    return raw, hashlib.sha256(raw).hexdigest()


def yahoo(t):
    p1, p2 = _epoch("2000-01-01"), _epoch("2026-11-23")
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{t}?period1={p1}&period2={p2}"
           "&interval=1d&events=div,split")
    raw, sha = fetch(url, t.replace("^", "IDX_").replace("=", "_") + ".json")
    res = json.loads(raw)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(
        res["meta"]["exchangeTimezoneName"]).tz_localize(None).normalize()
    df = pd.DataFrame({"close": q["close"], "volume": q.get("volume"),
                       "adj": adj if adj else q["close"]}, index=idx, dtype=float)
    df = df[~df.index.duplicated(keep="last")]
    ev = res.get("events", {})
    divs = pd.Series({pd.to_datetime(int(k), unit="s").normalize(): v["amount"]
                      for k, v in ev.get("dividends", {}).items()}, dtype=float).sort_index()
    splits = [{"date": str(pd.to_datetime(int(k), unit="s").date()),
               "ratio": f'{v["numerator"]}:{v["denominator"]}'}
              for k, v in ev.get("splits", {}).items()]
    return df, divs, splits, res["meta"], sha


def dedup_dividends(divs, days=45):
    """Yahoo .JO lists many dividends twice (two dates, same amount, days apart). Keep the LAST
    of each run of equal amounts within `days` (taken as the ex-date)."""
    keep, items = [], list(divs.items())
    for i, (d, a) in enumerate(items):
        nxt = items[i + 1] if i + 1 < len(items) else None
        if nxt and abs(nxt[1] - a) < 1e-6 and (nxt[0] - d).days <= days:
            continue
        keep.append((d, a))
    return pd.Series(dict(keep), dtype=float)


def clean_close(c, thr=np.log(50)):
    """Drop single-bar spikes: a bar off from BOTH neighbours by more than exp(thr) in the same
    direction (50x for unit prints; 10% for FX, where Yahoo has stray Friday prints)."""
    c = c.dropna()
    c = c[c > 0]
    lp, ln = np.log(c / c.shift(1)), np.log(c / c.shift(-1))
    bad = ((lp > thr) & (ln > thr)) | ((lp < -thr) & (ln < -thr))
    return c[~bad], [str(i.date()) for i in c.index[bad]]


def rebuild_tr(c, divs):
    """Total-return index from cleaned close and de-duplicated dividends (same units, ZAc),
    reinvested at the ex-date close: r_t = (P_t + D_t) / P_{t-1} - 1."""
    d = divs.reindex(c.index).fillna(0.0)
    # dividends dated on non-trading days go to the next bar
    off = divs[~divs.index.isin(c.index)]
    for dt, a in off.items():
        nxt = c.index[c.index > dt]
        if len(nxt):
            d[nxt[0]] += a
    r = (c + d) / c.shift(1) - 1
    return (1 + r.fillna(0)).cumprod()


def check_series(t, df, divs, splits, meta):
    c = df["close"]
    good = c.dropna()
    good = good[good > 0]
    r = good.pct_change().dropna()
    gaps = good.index.to_series().diff().dt.days
    big_gaps = gaps[gaps > 7]
    # stale: longest run of identical closes
    same = (good.diff() == 0).astype(int)
    runs = same.groupby((same == 0).cumsum()).sum()
    jumps = r[r.abs() > 0.20]
    unit = r[(r > 50) | (r < -0.98)]
    # adjclose steps on dividend ex-dates: ratio adj/close should drop by ~div/prev close
    ratio = (df["adj"] / df["close"]).dropna()
    step = ratio.pct_change().dropna()
    div_chk = []
    for d, amt in divs.items():
        if d not in good.index:
            continue
        i = good.index.get_loc(d)
        if i == 0:
            continue
        prev = good.iloc[i - 1]
        expect = amt / prev
        # Yahoo applies the factor to bars BEFORE the ex-date: ratio rises at the ex-date
        got = step.get(d, np.nan)
        div_chk.append({"date": str(d.date()), "div_over_prev_close": round(expect, 5),
                        "ratio_step": None if pd.isna(got) else round(float(got), 5)})
    matched = [x for x in div_chk if x["ratio_step"] is not None
               and abs(x["ratio_step"] - x["div_over_prev_close"] / (1 - x["div_over_prev_close"]))
               <= 0.15 * x["div_over_prev_close"] + 1e-4]
    non_div_steps = step.drop([pd.Timestamp(x["date"]) for x in div_chk], errors="ignore")
    stray = non_div_steps[non_div_steps.abs() > 1e-4]
    # implied trailing dividend yield by calendar year (full years only)
    yld = {}
    if len(divs):
        ann = divs.groupby(divs.index.year).sum()
        px = good.groupby(good.index.year).mean()
        for y in ann.index:
            if y in px.index and pd.Timestamp(f"{y}-01-10") >= good.index[0] and y < 2026:
                yld[int(y)] = round(float(ann[y] / px[y]), 4)
    me = good.resample("ME").last()
    months_missing = int(me.isna().sum())
    vol0 = int((df["volume"] == 0).sum()) if "volume" in df else None
    return {
        "currency": meta.get("currency"), "first": str(good.index[0].date()),
        "last": str(good.index[-1].date()), "bars": int(len(good)),
        "nan_or_zero_close": int(len(c) - len(good)), "zero_volume_bars": vol0,
        "gaps_over_7_days": [{"end": str(i.date()), "days": int(v)} for i, v in big_gaps.items()][:15],
        "n_gaps_over_7_days": int(len(big_gaps)),
        "longest_identical_close_run": int(runs.max()) if len(runs) else 0,
        "daily_moves_over_20pct": [{"date": str(i.date()), "move": round(float(v), 3)}
                                   for i, v in jumps.items()],
        "unit_errors_100x": int(len(unit)), "splits": splits,
        "dividends": int(len(divs)), "dividend_steps_matched": len(matched),
        "dividend_steps_checked": len(div_chk),
        "adj_ratio_steps_off_dividend_dates": int(len(stray)),
        "adj_differs_from_close": bool((ratio.max() - ratio.min()) > 1e-6),
        "implied_dividend_yield_by_year_RAW_yahoo": yld, "month_ends_missing": months_missing,
    }


def fred(s):
    raw, sha = fetch(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}", f"{s}.csv")
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = ["date", "v"]
    df["date"] = pd.to_datetime(df["date"])
    v = pd.to_numeric(df.set_index("date")["v"], errors="coerce")
    return v, sha


def main():
    out = {"generated": TODAY, "holdout_start": str(HOLDOUT_START.date()), "series": {},
           "sha256": {}, "notes": []}
    adj_m, close_d = {}, {}
    for t, (cls, role) in YAHOO.items():
        df, divs, splits, meta, sha = yahoo(t)
        info = check_series(t, df, divs, splits, meta)
        info.update({"class": cls, "role": role,
                     "yahoo_firstTradeDate": str(pd.to_datetime(meta.get("firstTradeDate"), unit="s").date())
                     if meta.get("firstTradeDate") else None})
        out["series"][t] = info
        out["sha256"][t] = sha
        cc, bad = clean_close(df["close"], np.log(1.10) if role == "converter" else np.log(50))
        dd = dedup_dividends(divs) if len(divs) else divs
        info["single_bar_unit_prints_removed"] = bad
        info["dividends_after_dedup"] = int(len(dd))
        yd = {}
        if len(dd):
            ann = dd.groupby(dd.index.year).sum()
            px = cc.groupby(cc.index.year).mean()
            yd = {int(y): round(float(ann[y] / px[y]), 4) for y in ann.index
                  if y in px.index and pd.Timestamp(f"{y}-01-10") >= cc.index[0] and y < 2026}
        info["implied_dividend_yield_by_year_dedup"] = yd
        # completeness of Yahoo's dividend record (only for series that distribute)
        if len(dd):
            yrs = range(cc.index[0].year, 2027)
            cnt = dd.groupby(dd.index.year).size()
            mode = int(cnt.mode().iloc[0])
            per_event = dd / cc.reindex(dd.index, method="nearest")
            med = float(per_event.median())
            info["dividend_count_by_year"] = {int(y): int(cnt.get(y, 0)) for y in yrs}
            info["years_with_bars_but_no_dividend"] = [int(y) for y in yrs if cnt.get(y, 0) == 0]
            info["years_below_usual_count"] = [int(y) for y in yrs if 0 < cnt.get(y, 0) < mode]
            # event yield < 1/20 of the median event yield: amount probably in ZAR, not ZAc
            info["suspect_unit_switch_events"] = [str(d.date()) for d, v in per_event.items()
                                                  if v < med / 20]
        tr = rebuild_tr(cc, dd) if len(dd) else cc / cc.iloc[0]
        g = tr if role != "converter" else cc
        adj_m[t] = g.resample("ME").last()
        close_d[t] = g
    for s in FRED:
        v, sha = fred(s)
        out["sha256"][s] = sha
        v = v.dropna()
        out["series"][s] = {"first": str(v.index[0].date()), "last": str(v.index[-1].date()),
                            "months": int(len(v)), "missing_months": int(
                                len(pd.date_range(v.index[0], v.index[-1], freq="MS")) - len(v)),
                            "min": float(v.min()), "max": float(v.max())}
        if s == "IRLTLT01ZAM156N":
            y = v.copy()
            y.index = y.index + pd.offsets.MonthEnd(0)
            r = y.shift(1) / 1200 - D_BOND * y.diff() / 100
            adj_m["SYNTH_BOND"] = (1 + r.dropna()).cumprod()
    # URTH in ZAR
    fx = close_d["USDZAR=X"].resample("ME").last()
    adj_m["URTH_ZAR"] = (adj_m["URTH"] * fx).dropna()

    pre = HOLDOUT_START - pd.offsets.MonthEnd(1)
    track = []
    for a, b in PAIRS:
        ra = adj_m[a].pct_change()
        rb = adj_m[b].pct_change()
        j = pd.concat([ra, rb], axis=1, keys=["a", "b"]).dropna()
        j = j[j.index <= pre]
        if len(j) < 6:
            track.append({"proxy": a, "target": b, "months": int(len(j)), "note": "overlap < 6 months"})
            continue
        te = float((j["a"] - j["b"]).std() * np.sqrt(12))
        track.append({"proxy": a, "target": b, "months": int(len(j)),
                      "from": str(j.index[0].date()), "to": str(j.index[-1].date()),
                      "corr": round(float(j.corr().iloc[0, 1]), 3),
                      "tracking_error_annual": round(te, 4),
                      "vol_ratio": round(float(j["a"].std() / j["b"].std()), 3)})
    out["tracking_pre_holdout_monthly"] = track

    end = min(adj_m[t].dropna().index[-1] for t in ["STX40.JO"])
    windows = {}
    for name, m in SETS.items():
        starts = {c: str(adj_m[s].dropna().index[0].date()) for c, s in m.items()}
        start = max(adj_m[s].dropna().index[0] for s in m.values())
        months = len(pd.date_range(start, end, freq="ME"))
        last40 = pd.date_range(start, end, freq="ME")[int(round(0.6 * months))]
        windows[name] = {"series": m, "class_starts": starts, "window_start": str(start.date()),
                         "window_end": str(end.date()), "months": months,
                         "vault_last40_start": str(last40.date()),
                         "dev_months_if_last40": int(round(0.6 * months)),
                         "dev_months_if_holdout_start": int(len(pd.date_range(start, HOLDOUT_START, freq="ME"))),
                         "vault_months_if_holdout_start": int(len(pd.date_range(HOLDOUT_START, end, freq="ME")))}
    out["windows"] = windows
    cash = out["series"]["IR3TIB01ZAM156N"]
    out["notes"].append(f"Cash leg IR3TIB01ZAM156N covers {cash['first']} to {cash['last']}.")
    os.makedirs("docs/results", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    for t, s in out["series"].items():
        if "bars" in s:
            print(f"{t:10s} {s['currency']} {s['first']}..{s['last']} bars {s['bars']} gaps>7d "
                  f"{s['n_gaps_over_7_days']} stale {s['longest_identical_close_run']} >20% "
                  f"{len(s['daily_moves_over_20pct'])} divs {s['dividends']} matched "
                  f"{s['dividend_steps_matched']}/{s['dividend_steps_checked']} stray "
                  f"{s['adj_ratio_steps_off_dividend_dates']} missingM {s['month_ends_missing']}")
        else:
            print(t, s)
    for x in track:
        print(x)
    for t, s in out["series"].items():
        if "dividends_after_dedup" in s:
            print(t, "dedup", s["dividends"], "->", s["dividends_after_dedup"], "bad prints",
                  s["single_bar_unit_prints_removed"], "no-div years", s.get("years_with_bars_but_no_dividend"),
                  "short years", s.get("years_below_usual_count"), "unit-switch", s.get("suspect_unit_switch_events"))
    for k, w in windows.items():
        print(k, {i: w[i] for i in w if i != "series"})


if __name__ == "__main__":
    main()
