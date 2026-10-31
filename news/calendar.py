"""The economic calendar: when the scheduled news is, so the engine does not trade into it.

Around a high-impact release (US jobs report, inflation, a central bank decision) prices jump in
seconds and the broker's spread widens many times over. A one-second shop cannot win that race,
so the first use of the calendar is defensive: no new entry from 30 minutes before to 30 minutes
after a high-impact event in a currency the instrument depends on.

Source: the Forex Factory weekly feed (`nfs.faireconomy.media`), free, no key, times in New York
time with an explicit offset. Every fetch is merged into `data/calendar.json`, so the engine
builds its own history from today on.

NOT used: the Hugging Face "Forex Factory 2007-2025" history. Checked 2026-10-31 against release
times that are fixed by law: only 58 of 220 US jobs reports sit at Friday 08:30 New York time
(most are 17 hours early, on Thursday afternoon) and 1 of 219 inflation releases is at 08:30.
A backtest that used it would put the news in the wrong place. Historical event studies need
official schedules (BLS, the Fed) instead.

Fail closed: if the calendar does not cover the moment asked about (no fetch this week), the
answer is "blocked: calendar missing", not "no news". Unknown is never treated as safe.

    python -m news.calendar            # fetch this week, merge, print the high-impact events
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import requests

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STORE = "data/calendar.json"
UA = {"User-Agent": "trading-research-engine (research; contact via GitHub LeparaLaMapara)"}
NY = ZoneInfo("America/New_York")

BEFORE_MIN, AFTER_MIN = 30, 30
BLOCKING_IMPACTS = ("High",)

#: Currencies an instrument moves with. FX pairs are split automatically; this covers the rest.
#: Crypto and gold trade against the dollar and react to US data, so they carry USD.
OTHER_CURRENCIES = {
    "XAUUSD": ("USD",), "XAGUSD": ("USD",), "XTIUSD": ("USD",), "XBRUSD": ("USD",),
    "US500": ("USD",), "US30": ("USD",), "USTEC": ("USD",), "US2000": ("USD",),
    "DE40": ("EUR",), "F40": ("EUR",), "STOXX50": ("EUR",), "UK100": ("GBP",),
    "JP225": ("JPY",), "AUS200": ("AUD",), "HK50": ("CNY",), "SA40": ("ZAR", "USD"),
}
CRYPTO = ("BTC", "ETH", "LTC", "BCH", "ADA", "XRP", "SOL", "DOT", "DOGE", "LNK", "XLM", "UNI")


def currencies_of(symbol: str) -> tuple[str, ...]:
    s = symbol.upper()
    if s in OTHER_CURRENCIES:
        return OTHER_CURRENCIES[s]
    if any(s.startswith(c) for c in CRYPTO):
        return ("USD",)
    if len(s) == 6 and s.isalpha():
        return (s[:3], s[3:])
    raise KeyError(f"no currency mapping for {symbol}; add it to news.calendar.OTHER_CURRENCIES")


@dataclass(frozen=True)
class Event:
    ts: float            # UTC epoch seconds
    currency: str
    impact: str          # High / Medium / Low / Holiday
    title: str
    forecast: str = ""
    previous: str = ""

    def key(self) -> str:
        return f"{int(self.ts)}|{self.currency}|{self.title}"


def week_start(ts: float) -> float:
    """Sunday 00:00 New York time of the week containing ts (the feed's week)."""
    d = dt.datetime.fromtimestamp(ts, NY)
    sunday = (d - dt.timedelta(days=(d.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0,
                                                                      microsecond=0)
    return sunday.timestamp()


def parse_feed(rows: list[dict]) -> list[Event]:
    out = []
    for r in rows:
        when = dt.datetime.fromisoformat(r["date"])
        if when.tzinfo is None:
            raise ValueError(f"feed time without an offset: {r['date']!r}")
        out.append(Event(when.timestamp(), r["country"].upper(), r.get("impact", ""),
                         r.get("title", ""), r.get("forecast", "") or "",
                         r.get("previous", "") or ""))
    return out


def load(path: str = STORE) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"weeks": [], "events": []}


def merge(store: dict, events: list[Event], fetched_ts: float) -> dict:
    """Add a fetch to the store. The week counts as covered only if the feed is for the week
    the fetch happened in (the feed always serves the current week)."""
    by_key = {f"{int(e['ts'])}|{e['currency']}|{e['title']}": e for e in store.get("events", [])}
    for e in events:
        by_key[e.key()] = e.__dict__ | {"fetched": int(fetched_ts)}
    weeks = set(store.get("weeks", []))
    if events and all(week_start(e.ts) == week_start(fetched_ts) for e in events
                      if e.impact != "Holiday"):
        weeks.add(int(week_start(fetched_ts)))
    return {"weeks": sorted(weeks),
            "events": sorted(by_key.values(), key=lambda e: (e["ts"], e["currency"]))}


def fetch(path: str = STORE, now: float | None = None) -> dict:
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    r = requests.get(FEED, headers=UA, timeout=30)
    r.raise_for_status()
    store = merge(load(path), parse_feed(r.json()), now)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=1)
    os.replace(tmp, path)
    return store


def blackout(symbol: str, ts: float, store: dict | None = None, before_min: int = BEFORE_MIN,
             after_min: int = AFTER_MIN) -> str | None:
    """Why `symbol` must not open at `ts`, or None if it may. Fails closed."""
    store = store if store is not None else load()
    if int(week_start(ts)) not in set(store.get("weeks", [])):
        return "calendar missing for this week (fail closed)"
    cur = set(currencies_of(symbol))
    lo, hi = ts - after_min * 60, ts + before_min * 60
    for e in store.get("events", []):
        if e["impact"] in BLOCKING_IMPACTS and e["currency"] in cur and lo <= e["ts"] <= hi:
            when = dt.datetime.fromtimestamp(e["ts"], dt.timezone.utc).strftime("%H:%M UTC")
            return f"news: {e['currency']} {e['title']} at {when}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=STORE)
    a = ap.parse_args()
    store = fetch(a.store)
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    ws = week_start(now)
    high = [e for e in store["events"] if e["impact"] == "High" and ws <= e["ts"] < ws + 7 * 86400]
    print(f"calendar: {len(store['events'])} events stored, {len(store['weeks'])} weeks covered; "
          f"{len(high)} high-impact this week")
    for e in high:
        print(f"  {dt.datetime.fromtimestamp(e['ts'], dt.timezone.utc):%a %d %b %H:%M} UTC  "
              f"{e['currency']}  {e['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
