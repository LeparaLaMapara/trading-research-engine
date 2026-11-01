"""Download Binance spot hourly klines (public, no key) from data.binance.vision into one CSV
per symbol: timestamp (ms UTC, bar open), open, high, low, close, volume.

    python scripts/fetch_binance_h1.py BTCUSDT ETHUSDT --out T:/making-money/features/intraday/crypto_h1

Binance switched spot timestamps to microseconds from 2025; both are normalised to ms.
Exchange prices have no bid/ask: costs come from the broker's measured spread.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import urllib.error
import urllib.request
import zipfile

URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/1h/{s}-1h-{y}-{m:02d}.zip"


def months(start=(2017, 8), end=(2026, 9)):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch(sym: str, out_dir: str) -> str:
    rows = []
    for y, m in months():
        try:
            raw = urllib.request.urlopen(URL.format(s=sym, y=y, m=m), timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = z.read(z.namelist()[0]).decode()
        for r in csv.reader(io.StringIO(text)):
            if not r or not r[0].isdigit():
                continue
            ts = int(r[0])
            ts = ts // 1000 if ts > 10**14 else ts
            rows.append((ts, r[1], r[2], r[3], r[4], r[5]))
    rows.sort()
    path = os.path.join(out_dir, f"{sym.lower()}-h1.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for s in a.symbols:
        p = fetch(s, a.out)
        print(s, p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
