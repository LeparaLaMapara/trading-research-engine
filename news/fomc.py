"""Scheduled FOMC statement dates, read from the Federal Reserve's own pages.

Used by E12 (the dollar on Fed decision days). Only SCHEDULED meetings count, as in Mueller,
Tahbaz-Salehi and Vedolin (2017): unscheduled meetings, cancelled meetings and notation votes
are left out. The statement day is the last day of the meeting.

  * 2021 onward: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm. A scheduled
    meeting has a statement link `monetaryYYYYMMDDa.htm` AND an implementation note
    `monetaryYYYYMMDDa1.htm`; a notation vote has only the first.
  * up to 2020: `fomchistoricalYYYY.htm`, whose panel headings read "June 9-10 Meeting - 2020"
    for a scheduled meeting and carry "(unscheduled)", "(cancelled)" or "(notation vote)"
    otherwise.

Every year must yield exactly 8 dates or the fetch fails: a wrong calendar must never reach a
backtest quietly.

    python -m news.fomc --from 2014 --to 2026      # writes data/fomc_dates.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (trading-research-engine research)"}
CURRENT = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
HISTORICAL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
OUT = "data/fomc_dates.json"
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}


def from_current_page(html: str) -> list[str]:
    a = set(re.findall(r"monetary(\d{8})a\.htm", html))
    a1 = set(re.findall(r"monetary(\d{8})a1\.htm", html))
    return sorted(f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in a & a1)


def cancelled_count(html: str) -> int:
    return len(re.findall(r"<h5[^>]*>[^<]*\(cancelled\) Meeting - \d{4}</h5>", html))


def from_historical_page(html: str, year: int) -> list[str]:
    out = []
    for head in re.findall(r"<h5[^>]*>([^<]*Meeting - \d{4})</h5>", html):
        if "(" in head:
            continue                                   # unscheduled / cancelled
        m = re.match(r"\s*([A-Za-z]+)(?:/([A-Za-z]+))?\s+(\d+)(?:-(\d+))?\s+Meeting", head)
        if not m:
            raise ValueError(f"unrecognised meeting heading: {head!r}")
        first, second, d1, d2 = m.groups()
        name = second or first          # "Jan/Feb 31-1": the statement is in the second month
        month = next((v for k, v in MONTHS.items() if k.startswith(name)), None) \
            if len(name) >= 3 else None
        if month is None:
            raise ValueError(f"unrecognised month in heading: {head!r}")
        day = int(d2 or d1)
        out.append(dt.date(year, month, day).isoformat())
    return sorted(out)


def fetch(start: int, end: int) -> dict[int, list[str]]:
    years: dict[int, list[str]] = {}
    cancelled: dict[int, int] = {}
    cur = requests.get(CURRENT, headers=UA, timeout=30)
    cur.raise_for_status()
    for d in from_current_page(cur.text):
        years.setdefault(int(d[:4]), []).append(d)
    for y in range(start, end + 1):
        if y in years:
            continue
        r = requests.get(HISTORICAL.format(year=y), headers=UA, timeout=30)
        r.raise_for_status()
        years[y] = from_historical_page(r.text, y)
        cancelled[y] = cancelled_count(r.text)
    out = {y: sorted(years.get(y, [])) for y in range(start, end + 1)}
    this_year = dt.date.today().year
    # 8 a year, less any the Fed cancelled (March 2020); the current year only up to today.
    bad = {y: len(v) for y, v in out.items()
           if (y < this_year and len(v) != 8 - cancelled.get(y, 0))
           or (y == this_year and not 0 < len(v) <= 8) or y > this_year}
    if bad:
        raise ValueError(f"expected 8 scheduled meetings a year, got {bad}")
    return out


def load(path: str = OUT) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [d for v in json.load(fh)["years"].values() for d in v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=2014)
    ap.add_argument("--to", dest="end", type=int, default=2026)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    years = fetch(a.start, a.end)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"source": [CURRENT, HISTORICAL], "fetched": dt.date.today().isoformat(),
                   "years": {str(k): v for k, v in years.items()}}, fh, indent=1)
    print(f"{sum(len(v) for v in years.values())} scheduled statements {a.start}-{a.end} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
