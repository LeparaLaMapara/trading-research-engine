"""Outside data the literature says matters, fetched from free public sources.

The engine had one data source, the broker's prices. The documented edges in currencies and
crypto come from elsewhere: interest-rate differences (carry), how speculators are positioned,
and what crypto perpetual futures pay each other (funding). This fetches those, without keys:

  rates    FRED (St. Louis Fed) CSV downloads: policy and 3-month interbank rates
  cot      CFTC Commitments of Traders, legacy futures-only report, via its public API
  funding  crypto perpetual funding: Binance monthly archive files (ETH, BTC), BitMEX history,
           OKX for the most recent months

Each source is written as a Parquet file with a SHA-256 in `manifest.json`, so any result can
say exactly which data it used. A series that fails to download is listed in the manifest as
failed; nothing is filled in or guessed.

    python -m data_ext.fetch --out data/external
    gh workflow run databricks-run.yml -f module=data_ext.fetch \
        -f args="--out /Volumes/workspace/trading_engine/external"
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import time
import zipfile

import pandas as pd
import requests

UA = {"User-Agent": "trading-research-engine (research; contact via GitHub LeparaLaMapara)"}

#: FRED series: (id, currency, what it is). Monthly OECD 3-month interbank rates where a daily
#: policy rate is not on FRED. Singapore has no FRED rate; SGD carry needs MAS data (not yet).
FRED = [
    ("DFF", "USD", "effective federal funds rate, daily"),
    ("ECBDFR", "EUR", "ECB deposit facility rate, daily"),
    ("IUDSOIA", "GBP", "SONIA, daily"),
    ("IRSTCI01JPM156N", "JPY", "Japan call money rate, monthly"),
    ("IR3TIB01AUM156N", "AUD", "Australia 3-month interbank, monthly"),
    ("IR3TIB01NZM156N", "NZD", "New Zealand 3-month interbank, monthly"),
    ("IR3TIB01CAM156N", "CAD", "Canada 3-month interbank, monthly"),
    ("IR3TIB01CHM156N", "CHF", "Switzerland 3-month interbank, monthly"),
    ("IR3TIB01EZM156N", "EUR", "euro area 3-month interbank, monthly"),
    ("IR3TIB01GBM156N", "GBP", "UK 3-month interbank, monthly"),
]

#: CFTC market names (legacy futures-only report), grouped by the instrument they describe. The
#: CFTC renamed several markets over the years (the pound became "BRITISH POUND" in 2022), so
#: each instrument lists every name it has had; `instrument` joins them into one series.
COT_MARKETS = {
    "AUD": ["AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE"],
    "CAD": ["CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE"],
    "GBP": ["POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
            "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
            "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE"],
    "EUR": ["EURO FX - CHICAGO MERCANTILE EXCHANGE"],
    "EURGBP": ["EURO FX/BRITISH POUND XRATE - CHICAGO MERCANTILE EXCHANGE"],
    "JPY": ["JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE"],
    "NZD": ["NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
            "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE"],
    "CHF": ["SWISS FRANC - CHICAGO MERCANTILE EXCHANGE"],
    "XAU": ["GOLD - COMMODITY EXCHANGE INC."],
    "ETH": ["ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE"],
    "BTC": ["BITCOIN - CHICAGO MERCANTILE EXCHANGE"],
}
COT_API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
COT_COLS = ["market_and_exchange_names", "report_date_as_yyyy_mm_dd", "open_interest_all",
            "noncomm_positions_long_all", "noncomm_positions_short_all",
            "comm_positions_long_all", "comm_positions_short_all",
            "nonrept_positions_long_all", "nonrept_positions_short_all"]

FUNDING_SYMBOLS = ["ETHUSDT", "BTCUSDT"]


def get(url: str, **kw) -> requests.Response:
    for attempt in range(4):
        r = requests.get(url, headers=UA, timeout=60, **kw)
        if r.status_code not in (429, 500, 502, 503, 504):
            return r
        time.sleep(5 * (attempt + 1))
    return r


# --------------------------------------------------------------------------- sources

def fetch_rates() -> tuple[pd.DataFrame, list[str]]:
    frames, failed = [], []
    for sid, ccy, what in FRED:
        r = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
        if r.status_code != 200 or not r.text.startswith("observation_date"):
            failed.append(f"FRED {sid}: HTTP {r.status_code}")
            continue
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")      # FRED uses "." for gaps
        df = df.dropna()
        df["date"] = pd.to_datetime(df["date"])
        df["series"], df["currency"], df["description"] = sid, ccy, what
        frames.append(df)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), failed


def fetch_cot() -> tuple[pd.DataFrame, list[str]]:
    by_name = {n: inst for inst, names in COT_MARKETS.items() for n in names}
    names = ",".join("'" + m.replace("'", "''") + "'" for m in by_name)
    rows, failed, offset = [], [], 0
    while True:
        r = get(COT_API, params={"$select": ",".join(COT_COLS),
                                 "$where": f"market_and_exchange_names in ({names})",
                                 "$order": "report_date_as_yyyy_mm_dd", "$limit": 50000,
                                 "$offset": offset})
        if r.status_code != 200:
            failed.append(f"CFTC: HTTP {r.status_code} {r.text[:120]}")
            break
        page = r.json()
        rows += page
        if len(page) < 50000:
            break
        offset += 50000
    df = pd.DataFrame(rows)
    if df.empty:
        return df, failed or ["CFTC: no rows"]
    df["date"] = pd.to_datetime(df.pop("report_date_as_yyyy_mm_dd"))
    df = df.rename(columns={"market_and_exchange_names": "market"})
    df["market"] = df["market"].str.strip()          # the API pads some names
    df["instrument"] = df["market"].map({k.strip(): v for k, v in by_name.items()})
    for c in df.columns:
        if c not in ("market", "date", "instrument"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["noncomm_net"] = df["noncomm_positions_long_all"] - df["noncomm_positions_short_all"]
    df["noncomm_net_share_of_oi"] = df["noncomm_net"] / df["open_interest_all"]
    got = set(df["instrument"])
    failed += [f"CFTC: no rows for {i}" for i in COT_MARKETS if i not in got]
    return df, failed


def _months(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_funding() -> tuple[pd.DataFrame, list[str]]:
    """Funding paid on USDT-margined perpetuals, every 8 hours. Positive means longs pay."""
    frames, failed = [], []
    last_full = (dt.date.today().replace(day=1) - dt.timedelta(days=1))
    for sym in FUNDING_SYMBOLS:
        got = 0
        for y, m in _months(dt.date(2019, 9, 1), last_full):
            url = (f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/"
                   f"{sym}-fundingRate-{y}-{m:02d}.zip")
            r = get(url)
            if r.status_code == 404:
                continue                       # the symbol had not listed yet
            if r.status_code != 200:
                failed.append(f"Binance {sym} {y}-{m:02d}: HTTP {r.status_code}")
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                raw = z.read(z.namelist()[0]).decode()
            df = pd.read_csv(io.StringIO(raw))
            df.columns = [c.strip().lower() for c in df.columns]
            tcol = next(c for c in df.columns if "time" in c)
            rcol = next(c for c in df.columns if "rate" in c and "funding" in c)
            frames.append(pd.DataFrame({
                "ts": pd.to_datetime(pd.to_numeric(df[tcol]), unit="ms", utc=True),
                "rate": pd.to_numeric(df[rcol]), "symbol": sym, "venue": "binance"}))
            got += 1
        if not got:
            failed.append(f"Binance {sym}: no monthly files")
        inst = sym.replace("USDT", "-USDT-SWAP")      # OKX: the current, unarchived month
        r = get("https://www.okx.com/api/v5/public/funding-rate-history",
                params={"instId": inst, "limit": 100})
        if r.status_code == 200 and r.json().get("data"):
            d = pd.DataFrame(r.json()["data"])
            frames.append(pd.DataFrame({
                "ts": pd.to_datetime(pd.to_numeric(d["fundingTime"]), unit="ms", utc=True),
                "rate": pd.to_numeric(d["fundingRate"]), "symbol": sym, "venue": "okx"}))
        else:
            failed.append(f"OKX {inst}: HTTP {r.status_code}")
    start = "2018-01-01T00:00:00Z"                    # BitMEX: a second venue, back to 2018
    while True:
        r = get("https://www.bitmex.com/api/v1/funding",
                params={"symbol": "ETHUSD", "count": 500, "startTime": start, "reverse": "false"})
        if r.status_code != 200:
            failed.append(f"BitMEX ETHUSD: HTTP {r.status_code}")
            break
        page = r.json()
        if not page:
            break
        d = pd.DataFrame(page)
        frames.append(pd.DataFrame({"ts": pd.to_datetime(d["timestamp"], utc=True),
                                    "rate": pd.to_numeric(d["fundingRate"]),
                                    "symbol": "ETHUSD", "venue": "bitmex"}))
        if len(page) < 500:
            break
        start = (pd.to_datetime(page[-1]["timestamp"]) + pd.Timedelta(seconds=1)).isoformat()
        time.sleep(1.5)                                # BitMEX allows about 30 requests a minute
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df = df.drop_duplicates(["venue", "symbol", "ts"]).sort_values(["venue", "symbol", "ts"])
    return df, failed


# --------------------------------------------------------------------------- main

SOURCES = {"rates": fetch_rates, "cot": fetch_cot, "funding": fetch_funding}


def write(df: pd.DataFrame, path: str) -> str:
    df.to_parquet(path, index=False)
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data/external")
    ap.add_argument("--only", nargs="*", choices=list(SOURCES))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    manifest = {"fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": {}}
    for name in a.only or SOURCES:
        t0 = time.time()
        try:
            df, failed = SOURCES[name]()
        except Exception as exc:  # noqa: BLE001 - one broken source must not stop the others
            df, failed = pd.DataFrame(), [f"{name}: {type(exc).__name__}: {exc}"]
        entry = {"rows": int(len(df)), "failed": failed, "seconds": round(time.time() - t0)}
        if not df.empty:
            tcol = "ts" if "ts" in df.columns else "date"
            entry.update(sha256=write(df, os.path.join(a.out, f"{name}.parquet")),
                         first=str(df[tcol].min()), last=str(df[tcol].max()))
        manifest["sources"][name] = entry
        print(f"{name}: {entry['rows']} rows, {len(failed)} failures, {entry['seconds']} s")
        for f in failed:
            print(f"  failed: {f}")
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    ok = all(v["rows"] for v in manifest["sources"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
