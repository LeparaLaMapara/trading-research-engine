"""E17 news reader: read official feeds, score each new item once with the local model, and turn
the scores into an hourly currency signal for the scoreboard's `news` player.

    python -m news.reader            # one pass: fetch every feed, score up to 6 new items
    python -m news.reader --status   # what the store holds

Rules (docs/programme/E17-news-reader-prereg.md): the first run marks everything already in the
feeds as backlog, never scored; items published more than 24 h before they are fetched are
stale; only items scored before hour H count for hour H. Runs on this PC only; nothing about
the account is ever sent to the model.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time

from news import feeds as FD

STORE = os.environ.get("NEWS_STORE", "data/news/items.jsonl")
SOURCES = os.environ.get("NEWS_SOURCES", "data/news/sources.json")
CODES = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")
# Currencies and metals that can make up an instrument but get no signal of their own.
OTHER = {"XAU", "XAG", "XPT", "XPD", "NOK", "SEK", "ZAR", "MXN", "PLN", "SGD"}
STALE_S = 24 * 3600
WINDOW_S = 24 * 3600
HALF_LIFE_H = 6.0          # weight exp(-age_hours / 6)
SIZE = 0.25                # predicted move = 0.25 x signal, in 24 h volatility units
MAX_FAILS = 3
VERSION = "n1"

SYSTEM = ("You are a careful macro analyst. You read one official release from a central bank or "
          "statistics office and judge only what it means for currencies over the next day. Most "
          "releases (speeches, appointments, research, routine notices) mean nothing for currencies: "
          "then every number is 0. Never guess. Reply with JSON only.")

PROMPT = """Publisher: {publisher} (its currency: {ccy})
Title: {title}
Published (UTC): {published}
Feed summary: {summary}
Page text (may be cut short): {text}

For each currency USD EUR GBP JPY CHF CAD AUD NZD give a number from -1 (this release should
weaken it) to 1 (strengthen it); 0 means no effect. Also give "confidence" from 0 to 1 for how
sure you are, and "why" in one short sentence. Reply as JSON with exactly the keys
USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, confidence, why."""


def _rows(path: str | None = None) -> list[dict]:
    path = path or STORE
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:      # a line cut short by a crash; the rest still counts
                continue
    return out


def _append(rows: list[dict], path: str | None = None) -> None:
    path = path or STORE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def _clip(x, lo: float, hi: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) else max(lo, min(hi, v))


def score_item(item: dict, port, text_fn=FD.page_text) -> dict:
    src, ccy = item["source"], FD.FEEDS.get(item["source"], ("", "?"))[1]
    pub = (time.strftime("%Y-%m-%d %H:%M", time.gmtime(item["published_utc"]))
           if item.get("published_utc") else "unknown")
    prompt = PROMPT.format(publisher=src, ccy=ccy, title=item["title"], published=pub,
                           summary=item.get("summary", "")[:1500] or "(none)",
                           text=text_fn(item.get("link", "")) or "(not available)")
    parsed, answers = port.complete_json(prompt, CODES + ("confidence", "why"), system=SYSTEM, max_tokens=300)
    last = answers[-1] if answers else None
    base = {"id": item["id"], "scored_utc": time.time(), "model": getattr(last, "model", None),
            "request_key": getattr(last, "request_key", None), "version": VERSION}
    if parsed is None:
        return base | {"kind": "score_failed", "error": "no valid JSON"}
    return base | {"kind": "score", "scores": {c: _clip(parsed.get(c), -1, 1) for c in CODES},
                   "confidence": _clip(parsed.get("confidence"), 0, 1), "why": str(parsed.get("why", ""))[:300]}


def run_once(now: float | None = None, fetch_fn=FD.fetch, text_fn=FD.page_text, port=None,
             max_items: int = 6, path: str | None = None, sources_path: str | None = None, log=print) -> dict:
    now = time.time() if now is None else now
    rows = _rows(path)
    first_run = not rows
    seen = {r["id"] for r in rows if r.get("kind") == "item"}
    health, new = {}, []
    for src in FD.FEEDS:
        try:
            items = fetch_fn(src)
            health[src] = {"ok_utc": now, "items": len(items)}
        except Exception as e:                       # a dead feed is shown, never replaced
            health[src] = {"error": str(e)[:200], "at_utc": now}
            continue
        for it in items:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            pub = it.get("published_utc")
            status = ("backlog" if first_run else
                      "stale" if pub is not None and now - pub > STALE_S else "new")
            new.append({"kind": "item", "fetched_utc": now, "status": status, **it})
    _append(new, path)
    sp = sources_path or SOURCES
    os.makedirs(os.path.dirname(sp) or ".", exist_ok=True)
    with open(sp, "w", encoding="utf-8") as fh:
        json.dump(health, fh, indent=1)

    rows = rows + new
    done = {r["id"] for r in rows if r.get("kind") == "score"}
    fails: dict[str, int] = {}
    for r in rows:
        if r.get("kind") == "score_failed":
            fails[r["id"]] = fails.get(r["id"], 0) + 1
    todo = sorted((r for r in rows if r.get("kind") == "item" and r["status"] == "new"
                   and r["id"] not in done and fails.get(r["id"], 0) < MAX_FAILS
                   and now - r["fetched_utc"] < WINDOW_S), key=lambda r: r["fetched_utc"])
    scored = []
    if todo:
        if port is None:
            from forecast import llm
            port = llm.port()
        for it in todo[:max_items]:
            try:
                s = score_item(it, port, text_fn)
            except Exception as e:
                s = {"kind": "score_failed", "id": it["id"], "scored_utc": time.time(), "error": str(e)[:200]}
            _append([s], path)
            scored.append(s)
            log(f"{s['kind']}: {it['source']} {it['title'][:70]}")
    out = {"new_items": len(new), "first_run": first_run, "scored": len(scored), "waiting": max(0, len(todo) - len(scored)),
           "dead_feeds": sorted(k for k, v in health.items() if "error" in v)}
    log(json.dumps(out))
    return out


def signal(hour: int, path: str | None = None) -> tuple[dict[str, float], list[str]]:
    """Each currency's signal for hour H from items scored before H and fetched in the 24 h before H."""
    rows = _rows(path)
    fetched = {r["id"]: r["fetched_utc"] for r in rows if r.get("kind") == "item"}
    sig = {c: 0.0 for c in CODES}
    used = []
    for r in rows:
        if r.get("kind") != "score" or r.get("version") != VERSION or r["scored_utc"] >= hour:
            continue
        f = fetched.get(r["id"])
        if f is None or not (hour - WINDOW_S < f < hour):
            continue
        w = r["confidence"] * math.exp(-((hour - f) / 3600) / HALF_LIFE_H)
        if w == 0 or not any(r["scores"].values()):
            continue
        for c in CODES:
            sig[c] += r["scores"].get(c, 0.0) * w
        used.append(r["id"])
    return sig, used


def instrument_signal(symbol: str, sig: dict[str, float]) -> float:
    """signal(first three letters) minus signal(last three); 0 when either half is not a currency
    or metal, so crypto, indices and oil get no view."""
    if len(symbol) != 6:
        return 0.0
    a, b = symbol[:3], symbol[3:]
    known = set(CODES) | OTHER
    if a not in known or b not in known:
        return 0.0
    return sig.get(a, 0.0) - sig.get(b, 0.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        rows = _rows()
        kinds = {}
        for r in rows:
            k = r.get("kind") if r.get("kind") != "item" else "item:" + r["status"]
            kinds[k] = kinds.get(k, 0) + 1
        print(json.dumps(kinds, indent=1))
        sig, used = signal(int(time.time()) // 3600 * 3600 + 3600)
        print("signal for next hour:", {k: round(v, 3) for k, v in sig.items() if v}, f"({len(used)} items)")
        return 0
    run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
