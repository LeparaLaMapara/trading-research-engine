"""The family-facing dashboard.

Audience: Thabang's family, who do not trade and should not have to learn. The first screen
(the family section, server rendered, one phone screen) answers in rand and short sentences:

    What is this?
    How much went in, what is it worth now, is it up or down?
    What is it doing right now?
    What is the most it can lose before it switches itself off?
    How does it decide?

Jargon is not simplified here, it is removed. Everything technical (research experiments,
self-checks, charts, the old daily search, the technical table) sits below in <details>
blocks for the owner. If a number cannot be stated in rands it does not belong up top.

The chat is an instruction channel: a person types a goal in their own words, an LLM fills in
the blanks it implies, and DETERMINISTIC code decides whether the arithmetic permits it
(`research/goals.py`). The reply is in rands and is allowed to say no.

One hard boundary, which is rule one of this project: **nothing typed here can place a trade.**
The chat writes goals. The research loop reads goals. The risk layer has no path from either.
A sentence must never become an order.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import time
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from config import settings
from dashboard.story import _currency_words, read_universe, story_html
from research.goals import GoalSpec, assess, suggest_reachable

app = FastAPI(title="Trading research")

ZAR_PER_USD = float(os.environ.get("ZAR_PER_USD", "18.0"))
# Goals drive the research system, so writing one requires the shared password. Reading the
# dashboard does not. Without a password set, the goal channel stays closed rather than open.
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
_SECRET = (os.environ.get("DASHBOARD_SECRET") or DASHBOARD_PASSWORD or "unset").encode()
# Writing needs the service-role key. With only the public read key the page still works and
# says plainly that the goal channel is read-only.
WRITE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
READ_KEY = settings.SUPABASE_KEY or ""


def _token() -> str:
    return hmac.new(_SECRET, b"dashboard-v1", hashlib.sha256).hexdigest()[:32]


def _authed(request: Request) -> bool:
    return bool(DASHBOARD_PASSWORD) and request.cookies.get("auth") == _token()


def _sb(table: str, query: str = "", key: str = "") -> list[dict]:
    k = key or READ_KEY
    if not (settings.SUPABASE_URL and k):
        return []
    try:
        r = requests.get(f"{settings.SUPABASE_URL}/rest/v1/{table}?{query}",
                         headers={"apikey": k, "Authorization": f"Bearer {k}",
                                  # This project's tables live in their own schema, not public.
                                  "Accept-Profile": settings.SUPABASE_SCHEMA}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def _sb_insert(table: str, row: dict) -> dict | None:
    if not (settings.SUPABASE_URL and WRITE_KEY):
        return None
    try:
        r = requests.post(f"{settings.SUPABASE_URL}/rest/v1/{table}",
                          headers={"apikey": WRITE_KEY,
                                   "Authorization": f"Bearer {WRITE_KEY}",
                                   "Content-Type": "application/json",
                                   "Content-Profile": settings.SUPABASE_SCHEMA,
                                   "Prefer": "return=representation"},
                          json=row, timeout=15)
        r.raise_for_status()
        out = r.json()
        return out[0] if isinstance(out, list) and out else None
    except Exception:
        return None


def _money(zar: float) -> str:
    return f"R{zar:,.0f}" if abs(zar) >= 1 else f"R{zar:,.2f}"


# ---------------------------------------------------------------- the family section
# The first screen is for people who know nothing about trading. It answers, in rand and in
# short sentences: what is this, how much went in, what is it worth, what is it doing, and
# how bad can it get. Everything else sits below, folded away, for the owner.
#
# The safety numbers are the owner-signed live limits (risk/limits.py LIVE_LIMITS). They are
# repeated here as plain constants on purpose: this page must never import live trading code.
RISK_PER_TRADE_PCT = 6          # at most 6% of the account risked on one trade
STOP_BELOW_PEAK = 0.40          # switches itself off 40% below the highest equity seen
STOP_FLOOR_USD = 20.0           # or below $20, whichever comes first
STALE_AFTER_S = 3 * 3600        # the engine publishes hourly; three hours quiet is worth saying
SA_UTC_OFFSET_S = 2 * 3600      # South African time, no daylight saving

# Words a family member should never meet in the family section.
FAMILY_BANNED = ("ETHUSD", "Sharpe", "null", "None", "nan", "pips", "slippage", "drawdown",
                 "p95", "E01", "E05", "E07")

_ASSET_WORDS = (("ETH", "Ethereum"), ("BTC", "Bitcoin"), ("XAU", "gold"), ("XAG", "silver"))


def _num(v) -> float | None:
    """A float, or None for missing, empty, or not-a-number values."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f             # NaN is not a number anyone should see


def _asset_word(symbol: str) -> str:
    s = (symbol or "").upper()
    for code, word in _ASSET_WORDS:
        if code in s:
            return word
    return "the market it is trading"


def _ago(ts: str | None, now: float) -> tuple[str, bool]:
    """('12 minutes ago (23 September, 07:55 SA time)', is_stale)."""
    from datetime import datetime, timezone
    if not ts:
        return "", False
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        epoch = t.timestamp()
    except (TypeError, ValueError):
        return "", False
    secs = max(0.0, now - epoch)
    mins = int(secs // 60)
    if mins < 1:
        rel = "just now"
    elif mins < 60:
        rel = f"{mins} minute{'s' if mins != 1 else ''} ago"
    elif mins < 48 * 60:
        h = round(mins / 60)
        rel = f"about {h} hour{'s' if h != 1 else ''} ago"
    else:
        d = mins // (24 * 60)
        rel = f"{d} days ago"
    sa = datetime.fromtimestamp(epoch + SA_UTC_OFFSET_S, tz=timezone.utc)
    when = f"{sa.day} {sa.strftime('%B')}, {sa.strftime('%H:%M')} SA time"
    return f"{rel} ({when})", secs > STALE_AFTER_S


def _halt_words(reason: str) -> str:
    r = (reason or "").lower()
    if "floor" in r:
        return (f"the money fell below ${STOP_FLOOR_USD:.0f} "
                f"(about {_money(STOP_FLOOR_USD * ZAR_PER_USD)}), the least it is allowed to "
                f"trade with")
    if "drawdown" in r or "peak" in r:
        return f"the money fell {STOP_BELOW_PEAK:.0%} below the most it has ever been worth"
    return "one of its safety limits was reached"


def max_loss_usd(equity: float | None, peak: float | None) -> float | None:
    """How far equity can fall before the engine switches itself off for good.

    The engine stops at the higher of (60% of the peak) and $20. The peak is at least the
    current equity: a stale peak below today's equity would understate the real line.
    """
    if equity is None:
        return None
    top = max(peak, equity) if peak is not None else equity
    stop_at = max((1.0 - STOP_BELOW_PEAK) * top, STOP_FLOOR_USD)
    return max(0.0, equity - stop_at)


def _family(acct: dict | None, open_positions: list[dict], now: float | None = None) -> dict:
    """The family section's facts and sentences. Pure: no network, never raises on NULLs."""
    now = time.time() if now is None else now
    a = acct or {}
    equity = _num(a.get("equity"))
    worth_usd = equity if equity is not None else _num(a.get("balance"))
    put_in_usd = _num(a.get("deposited_usd"))
    if put_in_usd is not None and put_in_usd <= 0:
        put_in_usd = None                  # nothing sensible to compare against
    peak = _num(a.get("peak_equity"))
    halted = (a.get("halted") or "").strip() if isinstance(a.get("halted"), str) else ""

    fam: dict = {"known": worth_usd is not None,
                 "worth_zar": None if worth_usd is None else worth_usd * ZAR_PER_USD,
                 "put_in_zar": None if put_in_usd is None else put_in_usd * ZAR_PER_USD,
                 "change_zar": None, "change_pct": None, "direction": None,
                 "halted": bool(halted), "halted_raw": halted}

    if fam["worth_zar"] is not None and fam["put_in_zar"] is not None:
        ch = fam["worth_zar"] - fam["put_in_zar"]
        fam["change_zar"] = ch
        fam["change_pct"] = 100.0 * ch / fam["put_in_zar"]
        fam["direction"] = "even" if abs(ch) < 1 else ("up" if ch > 0 else "down")

    # What it is doing right now.
    if halted:
        fam["halted_text"] = (f"The program has stopped itself for safety: "
                              f"{_halt_words(halted)}. It will not trade again unless Thabang "
                              f"restarts it.")
        fam["doing"] = "It is switched off and is not trading."
    elif open_positions:
        p0 = open_positions[0]
        what = _asset_word(p0.get("symbol") or "")
        way = "goes down" if (p0.get("side") or "").upper() == "SELL" else "goes up"
        pair = _currency_words(p0.get("symbol") or "")
        risks = [_num(p.get("risk_usd")) for p in open_positions]
        if all(r is not None for r in risks):
            loss = _money(sum(risks) * ZAR_PER_USD)
            tail = f"If it is wrong, it gets out automatically, losing at most about {loss}."
        else:
            tail = "If it is wrong, it gets out automatically at a price set in advance."
        if pair:
            rises = "falls" if way == "goes down" else "rises"
            fam["doing"] = f"It is betting the {pair[0]} {rises} against the {pair[1]}. {tail}"
        else:
            fam["doing"] = f"It is betting {what}'s price {way}. {tail}"
    else:
        fam["doing"] = "It is waiting for its next signal. It checks once a day."

    # The safety net.
    ml = max_loss_usd(equity if equity is not None else worth_usd, peak)
    fam["max_loss_zar"] = None if ml is None else ml * ZAR_PER_USD
    if halted:
        fam["safety"] = "It has already switched itself off, so it cannot lose more by trading."
    elif ml is None:
        fam["safety"] = ("The most it can lose before it switches itself off is not known yet. "
                         "It will show once the latest numbers arrive.")
    elif ml * ZAR_PER_USD < 1:
        fam["safety"] = "It is at its safety limit now, so it will switch itself off."
    else:
        fam["safety"] = (f"The most it can lose from here before it switches itself off: "
                         f"about {_money(ml * ZAR_PER_USD)}.")
    fam["safety_rule"] = (f"It never risks more than {RISK_PER_TRADE_PCT}% of the money on one "
                          f"trade.")

    ago, stale = _ago(a.get("ts"), now)
    fam["stale"] = stale
    if not ago:
        fam["updated"] = "The numbers have not been updated yet."
    elif stale:
        fam["updated"] = (f"Numbers last updated {ago}. That is longer than usual, so the "
                          f"computer running it may be off.")
    else:
        fam["updated"] = f"Numbers updated {ago}."
    return fam


FAMILY_INTRO = ("Thabang's experiment: a computer program that trades a small amount of money "
                "by itself, following rules that were tested on years of history first.")
FAMILY_HOW = ("How it decides: if a price rose over the last 20 days, it bets the price "
              "keeps rising, and if it fell, that it keeps falling. It gets out when the "
              "direction changes or its safety price is hit. It may only use a rule that "
              "passed its tests, so losing months are expected and sometimes it waits.")


def _family_html(fam: dict) -> str:
    """The family section as static HTML: readable with no JavaScript, on any screen."""
    esc = html.escape
    out = ["<section class='fam' id='family' aria-label='The short version'>",
           f"<p class='fam-intro'>{esc(FAMILY_INTRO)}</p>"]
    if fam.get("halted"):
        out.append(f"<p class='fam-halt' role='alert'>{esc(fam['halted_text'])}</p>")
    if not fam.get("known"):
        out.append("<p class='fam-now'>The latest numbers could not be loaded right now. "
                   "Please refresh in a few minutes.</p>")
    else:
        tiles = []
        if fam.get("put_in_zar") is not None:
            tiles.append(("Put in", _money(fam["put_in_zar"]), ""))
        tiles.append(("Worth now", _money(fam["worth_zar"]), ""))
        d = fam.get("direction")
        if d is not None:
            pct = fam["change_pct"]
            pct_s = f"{abs(pct):.0f}%" if abs(pct) >= 10 else f"{abs(pct):.1f}%"
            amt = _money(abs(fam["change_zar"]))
            if d == "up":
                tiles.append(("Up", f"<span aria-hidden='true'>&#9650;</span> {amt} "
                                    f"<small>({pct_s})</small>", "up"))
            elif d == "down":
                tiles.append(("Down", f"<span aria-hidden='true'>&#9660;</span> {amt} "
                                      f"<small>({pct_s})</small>", "down"))
            else:
                tiles.append(("Up or down", "About even", ""))
        out.append("<div class='fam-tiles'>" + "".join(
            f"<div class='fam-tile {cls}'><p class='fam-q'>{q}</p><p class='fam-n'>{v}</p>"
            f"</div>" for q, v, cls in tiles) + "</div>")
        if fam.get("put_in_zar") is None:
            out.append("<p class='fam-hint'>How much Thabang put in is still being fetched, so "
                       "the gain or loss will show soon.</p>")
        out.append(f"<p class='fam-now'><strong>Right now:</strong> {esc(fam['doing'])}</p>")
    out.append(f"<p><strong>Safety net:</strong> {esc(fam['safety'])} "
               f"{esc(fam['safety_rule'])}</p>")
    how_label, how_rest = FAMILY_HOW.split(": ", 1)
    out.append(f"<p><strong>{esc(how_label)}:</strong> {esc(how_rest)}</p>")
    out.append(f"<p class='fam-hint'>{esc(fam['updated'])} Amounts are in rand, at about "
               f"R{ZAR_PER_USD:.0f} to the US dollar.</p>")
    out.append("</section>")
    return "".join(out)


def _dashboard_data() -> dict:
    # select=* so the newer columns (deposited_usd, peak_equity, halted) arrive when present
    # and simply go missing, not break the query, on a table that lacks them.
    acct = _sb("trading_account", "select=*&order=ts.desc&limit=1")
    # The very first reading is the milestone baseline; the chart wants the newest 400.
    # (Ordering ascending with a limit stopped the chart at whatever day reading 400 fell on.)
    history = _sb("trading_account", "select=balance,ts&order=ts.asc&limit=1")
    recent = _sb("trading_account", "select=balance,ts&order=ts.desc&limit=1000")[::-1]
    strategies = _sb("trading_strategies",
                     "select=run_ts,symbol,kind,verdict,total_return,pnl_on_10,pnl_on_200,"
                     "dev_sharpe,holdout_sharpe&"
                     "order=run_ts.desc&limit=200")
    audit = _sb("ops_checks", "select=ran_at,check_id,status&order=ran_at.desc&limit=400")
    lessons = _sb("trading_lessons",
                  "select=lesson,evidence,times_seen,helped_rate&retired=eq.false&"
                  "order=helped_rate.desc&limit=8")
    goals = _sb("trading_goals",
                "select=created_ts,author,raw_text,status,target_zar,horizon_days,"
                "feasible,verdict_plain&order=created_ts.desc&limit=5", key=WRITE_KEY)

    balance_usd = (_num(acct[0].get("balance")) or 0.0) if acct else 0.0
    balance_zar = balance_usd * ZAR_PER_USD
    as_of = acct[0]["ts"] if acct else None

    # Real trading activity. Nothing here is modelled: these come from orders that were
    # actually sent to the broker. As of 2026-09-15 that is one attempt, rejected.
    # Real trading, read from the broker's own record (scripts/push_live_state publishes it
    # hourly). It used to come from environment variables a human had to remember to change,
    # which is why this panel said "0 trades" on the day a position was open.
    trades = _sb("trading_trades", "select=trade_id,ts,symbol,side,volume_lots,filled_price,"
                                   "net_usd,status,purpose,note&order=ts.desc&limit=300")
    positions = _sb("trading_positions",
                    "select=position_id,symbol,side,volume_lots,entry_price,current_price,"
                    "stop_loss,take_profit,unrealised_usd,risk_usd,swap_usd,opened_ts,updated_ts,status"
                    "&order=updated_ts.desc&limit=20")
    open_positions = [p for p in positions if (p.get("status") or "") == "OPEN"]

    # Probes and research trades are different things and must not be added together: a probe
    # is a measurement of execution cost, deliberately opened and closed at once.
    research = [t for t in trades if (t.get("purpose") or "") == "live_research_trade"]
    probes = [t for t in trades if (t.get("purpose") or "").startswith("telemetry")]
    attempted = len(research)
    executed = sum(1 for t in research if (t.get("status") or "").upper() == "FILLED")
    probes_done = sum(1 for t in probes if (t.get("status") or "").upper() in ("FILLED", "CLOSED"))
    realised = [float(t["net_usd"]) for t in trades if t.get("net_usd") is not None]
    made_zar = sum(x for x in realised if x > 0) * ZAR_PER_USD
    lost_zar = -sum(x for x in realised if x < 0) * ZAR_PER_USD
    unrealised_zar = sum(float(p.get("unrealised_usd") or 0.0) for p in open_positions) * ZAR_PER_USD
    # What is actually at risk right now: entry to stop, per open position, computed by the
    # publisher where the contract size is known.
    risked_zar = sum(float(p.get("risk_usd") or 0.0) for p in open_positions) * ZAR_PER_USD

    tested = len(strategies)
    passed = sum(1 for s in strategies if (s.get("verdict") or "").upper() == "PASS")
    last_run = strategies[0]["run_ts"] if strategies else None

    if open_positions:
        p0 = open_positions[0]
        exit_ = (f"falls to {p0.get('stop_loss')} or rises to {p0['take_profit']}"
                 if p0.get("take_profit") is not None else
                 f"reaches {p0.get('stop_loss')}, or when the direction changes (no profit "
                 f"target)")
        why = (f"It has {len(open_positions)} trade open right now: "
               f"{(p0.get('side') or '').lower()} {p0.get('symbol')}, opened at "
               f"{p0.get('entry_price')}, with an automatic exit if it {exit_}.")
    elif executed == 0 and passed == 0 and tested > 0:
        why = ("It has not traded. Every idea it tested so far lost money once real costs "
               "were counted, so it did not put any of yours at risk.")
    elif executed == 0 and tested == 0:
        why = ("It has not traded, and it has not finished testing anything yet either. "
               "Nothing is at risk.")
    elif executed == 0:
        why = ("It has not traded yet. Some ideas look promising but none has cleared the "
               "bar it is required to clear before real money moves.")
    else:
        why = f"It has placed {executed} trade(s)."

    # --- data shaped for the charts -------------------------------------------------
    # Balance in rands over time. One reading is not a line, and the chart says so
    # rather than drawing a flat stub that looks like a measurement.
    balance_series = [{"t": r["ts"], "v": float(r["balance"]) * ZAR_PER_USD} for r in recent
                      if _num(r.get("balance")) is not None and r.get("ts")]

    # What each tested idea WOULD have done to this stake. Hypothetical, from backtests,
    # and labelled as such everywhere it appears. Never mixed with real money.
    # One bar per IDEA, not per run. The same six kinds are re-tested on the same three
    # symbols every day, so plotting raw rows drew "vol_scaled XAUUSD" four times and made a
    # handful of ideas look like a crowd. Rows arrive newest first, so the first one wins.
    outcomes = []
    seen = set()
    for s in strategies:
        tr = s.get("total_return")
        key = (s.get("kind"), s.get("symbol"))
        if tr is None or key in seen:
            continue
        seen.add(key)
        hold = s.get("holdout_sharpe")
        outcomes.append({"label": f"{s.get('kind','?')} {s.get('symbol','')}".strip(),
                         "zar": float(tr) * balance_zar,
                         "pct": round(float(tr) * 100, 1),
                         "verdict": (s.get("verdict") or "").upper(),
                         # Did it still work on prices it had never seen? That is the number
                         # that decides, and it is why every positive bar below still failed.
                         "held_up": (None if hold is None else float(hold) > 0)})
        if len(outcomes) >= 18:
            break
    outcomes_passed = sum(1 for o in outcomes if o["verdict"] == "PASS")

    # Audit history as one row per check, one cell per day, most recent last.
    by_day: dict[str, dict[str, str]] = {}
    rank = {"PASS": 0, "UNKNOWN": 1, "FAIL": 2}
    for r in audit:
        day = (r.get("ran_at") or "")[:10]
        if not day:
            continue
        slot = by_day.setdefault(day, {})
        cid = r["check_id"]
        # Worst status wins for a day: a check that failed once that day did fail.
        if cid not in slot or rank.get(r["status"], 1) > rank.get(slot[cid], 0):
            slot[cid] = r["status"]
    days = sorted(by_day)[-21:]
    check_ids = sorted({c for d in by_day.values() for c in d})
    audit_grid = {"days": days, "checks": check_ids,
                  "cells": [[by_day.get(d, {}).get(c, "") for d in days] for c in check_ids]}

    from research.goals import milestone_progress, rebet_floor_zar
    # The owner's own funding condition: one 1% gain on what is already there unlocks the
    # next R5,000. Measured from the FIRST balance ever recorded, not the highest, so a
    # deposit cannot reset the bar. See research.goals.milestone_progress.
    baseline_zar = ((_num(history[0].get("balance")) or 0.0) * ZAR_PER_USD) if history else balance_zar
    milestone = milestone_progress(baseline_zar, balance_zar)

    goal_target = None
    for g in goals:
        if g.get("target_zar"):
            goal_target = float(g["target_zar"])
            break

    a0 = acct[0] if acct else None
    return {
        "family": _family(a0, open_positions),
        "equity_usd": _num((a0 or {}).get("equity")),
        "deposited_usd": _num((a0 or {}).get("deposited_usd")),
        "peak_equity_usd": _num((a0 or {}).get("peak_equity")),
        "halted": (a0 or {}).get("halted"),
        "have_zar": balance_zar,
        "have_usd": balance_usd,
        "as_of": as_of,
        "balance_series": balance_series,
        "outcomes": outcomes,
        "outcomes_passed": outcomes_passed,
        "audit_grid": audit_grid,
        "floor_zar": round(rebet_floor_zar(ZAR_PER_USD), 2),
        "milestone": milestone,
        "goal_target_zar": goal_target,
        "risked_zar": risked_zar,
        "made_zar": made_zar,
        "lost_zar": lost_zar,
        "attempted": attempted,
        "executed": executed,
        "probes_done": probes_done,
        "unrealised_zar": unrealised_zar,
        "open_positions": open_positions,
        "trades": trades,
        "ideas_tested": tested,
        "ideas_passed": passed,
        "last_run": last_run,
        "why_no_trade": why,
        "lessons": lessons,
        "goals": goals,
        "can_set_goals": bool(WRITE_KEY and DASHBOARD_PASSWORD),
        "configured": bool(settings.SUPABASE_URL and READ_KEY),
        "zar_per_usd": ZAR_PER_USD,
    }


@app.get("/api/data")
def api_data(request: Request) -> JSONResponse:
    d = _dashboard_data()
    if not _authed(request):
        # Who typed a goal, and the exact words, are private; the verdicts are not.
        d["goals"] = [{k: v for k, v in g.items() if k not in ("author", "raw_text")}
                      for g in d.get("goals") or []]
    return JSONResponse({**d, "programme": _programme_data()})


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/login")
async def api_login(request: Request) -> JSONResponse:
    body = await request.json()
    if DASHBOARD_PASSWORD and body.get("password") == DASHBOARD_PASSWORD:
        resp = JSONResponse({"ok": True})
        resp.set_cookie("auth", _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp
    return JSONResponse({"ok": False, "error": "Wrong password."}, status_code=401)


def _specialise(text: str, start_zar: float) -> dict:
    """Let a model fill in the blanks a wish implies. It decides NOTHING about feasibility.

    Falls back to defaults with no model at all, so the channel still works offline and the
    person still gets an honest answer.
    """
    spec = {"target_zar": round(start_zar * 2, 2), "horizon_days": 365,
            "risk_zar": round(start_zar * 0.64, 2), "assumed": True}
    try:
        from council.backends import get_backend
        backend = get_backend("anthropic")
        raw = backend.complete(
            "You convert a person's informal money goal into JSON. You do NOT judge whether "
            "it is achievable; other code does that. Reply with ONLY a JSON object with keys:\n"
            "  target_zar    the TOTAL BALANCE in rands they want to end up with, NOT the "
            "profit. It must be larger than their current balance.\n"
            "  horizon_days  integer, by when.\n"
            "  risk_zar      how much of the stake they seem willing to lose.\n"
            "  is_goal       false if the message is not a money goal at all (a greeting, a "
            "test, a question, chit-chat). When false, set the other fields to null.\n"
            "If they stated a goal but left out how much or by when, infer something "
            "reasonable and modest. Do NOT invent a goal out of a message that is not one.",
            f"Their current balance is R{start_zar:,.0f}. They said: {text!r}",
        )
        import json
        got = json.loads(raw)
        if got.get("is_goal") is False or got.get("target_zar") is None:
            # Not a goal. Manufacturing a target from a greeting produced a nonsense R200
            # objective in testing; saying so is better than inventing numbers.
            return {"not_a_goal": True, "target_zar": 0.0, "horizon_days": 0,
                    "risk_zar": 0.0, "assumed": False}
        target = float(got["target_zar"])
        # Guard the ambiguity the model keeps hitting: a "target" at or below the current
        # balance almost always means the PROFIT they want, not the end balance. Treat it as
        # profit rather than handing the person an absurd verdict about shrinking the account.
        assumed = False
        if target <= start_zar:
            target = start_zar + abs(target)
            assumed = True
        spec = {"target_zar": target,
                "horizon_days": max(int(got["horizon_days"]), 1),
                "risk_zar": float(got.get("risk_zar", start_zar * 0.64)),
                "assumed": assumed}
    except Exception:
        pass
    return spec


@app.post("/api/goal")
async def api_goal(request: Request) -> JSONResponse:
    """A person states a goal. We specialise it, judge it with arithmetic, and store it."""
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "Please sign in first."}, status_code=401)
    body = await request.json()
    text = (body.get("text") or "").strip()
    author = (body.get("author") or "family").strip()[:40]
    if not text:
        return JSONResponse({"ok": False, "error": "Say what you want to happen."}, status_code=400)

    data = _dashboard_data()
    start = data["have_zar"] or 1000.0
    s = _specialise(text, start)
    if s.get("not_a_goal"):
        return JSONResponse({"ok": True, "feasible": None, "reply":
            "That does not look like a money goal, so I have not recorded one. Tell me what "
            "you want to end up with and by when, for example: turn this into R2000 by "
            "December, and I can afford to lose half."})
    spec = GoalSpec(author=author, raw_text=text, target_zar=s["target_zar"],
                    horizon_days=s["horizon_days"], risk_zar=s["risk_zar"], start_zar=start)
    verdict = assess(spec, zar_per_usd=ZAR_PER_USD)
    alternatives = suggest_reachable(spec, zar_per_usd=ZAR_PER_USD)

    _sb_insert("trading_goals", {
        "author": author, "raw_text": text,
        "status": "specified" if verdict.feasible else "infeasible",
        "target_zar": spec.target_zar, "horizon_days": spec.horizon_days,
        "risk_zar": spec.risk_zar, "feasible": verdict.feasible,
        "required_return_pct": verdict.required_return_pct,
        "required_sharpe": verdict.required_sharpe,
        "ruin_probability": verdict.prob_hit_floor_no_edge,
        "verdict_plain": verdict.verdict_plain,
        "spec_json": {"feasibility": verdict.to_dict(), "alternatives": alternatives,
                      "inferred": s["assumed"]},
    })

    reply = verdict.verdict_plain + "\n\n" + verdict.context_plain
    if not verdict.feasible and alternatives.get("days_needed_at_world_class_skill"):
        reply += (f"\n\nWhat would make it reachable: about "
                  f"{alternatives['days_needed_at_world_class_skill']} days instead, or a "
                  f"stake of about R{alternatives['funding_for_1pct_risk_zar']:,.0f} so each "
                  f"trade risks a normal 1% instead of {verdict.risk_per_trade_pct:.0f}%.")
    if s["assumed"]:
        reply += ("\n\n(You did not say how much or by when, so I assumed doubling it within "
                  "a year. Tell me the real numbers and I will redo this.)")
    return JSONResponse({"ok": True, "reply": reply, "feasible": verdict.feasible,
                         "detail": verdict.to_dict()})


PAGE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Trading experiment</title>
<style>
  :root{--paper:#faf7f2;--ink:#1c1917;--muted:#6b6560;--line:#e7e0d6;--good:#2f6f4e;
        --bad:#a33a2a;--clay:#c2683f;--card:#fff}
  @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#16140f;
    --ink:#f2ede4;--muted:#a49c91;--line:#2e2a23;--card:#1e1b16;--good:#6fbf91;--bad:#e08370}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 ui-sans-serif,
       system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:0 16px 64px}
  .wrap{max-width:860px;margin:0 auto}
  header{padding:32px 0 8px}
  h1{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}
  .sub{color:var(--muted);font-size:15px;margin:0}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;
        margin:24px 0}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
  .q{color:var(--muted);font-size:14px;margin:0 0 6px}
  .n{font-size:32px;font-weight:650;letter-spacing:-.02em;margin:0}
  .n.good{color:var(--good)} .n.bad{color:var(--bad)}
  .hint{color:var(--muted);font-size:13px;margin:6px 0 0}
  .banner{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--clay);
          border-radius:12px;padding:16px 18px;margin:16px 0}
  h2{font-size:18px;margin:32px 0 10px}
  ul.lessons{list-style:none;padding:0;margin:0}
  ul.lessons li{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:14px 16px;margin-bottom:10px}
  ul.lessons .ev{color:var(--muted);font-size:13px;margin-top:4px}
  .chat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;
        margin-top:12px}
  textarea,input{width:100%;font:inherit;padding:12px;border:1px solid var(--line);
        border-radius:10px;background:var(--paper);color:var(--ink)}
  textarea{min-height:76px;resize:vertical}
  button{font:inherit;font-weight:600;padding:12px 18px;border:0;border-radius:10px;
        background:var(--clay);color:#fff;cursor:pointer;margin-top:10px;min-height:44px}
  button:disabled{opacity:.5;cursor:default}
  .reply{white-space:pre-wrap;margin-top:14px;padding:14px 16px;border-radius:10px;
        background:var(--paper);border:1px solid var(--line)}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
  .row>div{flex:1;min-width:160px}
  details{margin-top:28px;border-top:1px solid var(--line);padding-top:14px}
  summary{cursor:pointer;color:var(--muted);font-size:14px}
  table{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}
  td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
  .foot{color:var(--muted);font-size:13px;margin-top:28px}
  .tag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;
       border:1px solid var(--line);color:var(--muted)}

  /* --- visualisation roles. Dark steps are chosen for the dark surface, not flipped,
         and are declared under both the OS media query and the theme stamp. --- */
  .viz{color-scheme:light;
       --grid:#e7e0d6; --axis:#6b6560;
       --gain:#2a78d6;      /* diverging: money gained */
       --loss:#e34948;      /* diverging: money lost   */
       --mid:#f0efec;       /* neutral midpoint        */
       --line-1:#2a78d6;    /* single series           */
       --ok:#0ca30c; --unknown:#fab219; --bad:#d03b3b}   /* status, never themed */
  @media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz{
       color-scheme:dark; --grid:#2e2a23; --axis:#a49c91;
       --gain:#3987e5; --loss:#e66767; --mid:#383835; --line-1:#3987e5}}
  :root[data-theme="dark"] .viz{color-scheme:dark; --grid:#2e2a23; --axis:#a49c91;
       --gain:#3987e5; --loss:#e66767; --mid:#383835; --line-1:#3987e5}
  .viz{background:var(--card);border:1px solid var(--line);border-radius:14px;
       padding:18px;margin-bottom:12px;position:relative}
  .viz h3{font-size:15px;margin:0 0 2px;font-weight:650}
  .viz .cap{color:var(--muted);font-size:13px;margin:0 0 12px}
  .viz svg{width:100%;height:auto;display:block;overflow:visible;margin-inline:auto}
  .viz .empty{color:var(--muted);font-size:14px;padding:18px 0}
  .legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:13px;
          color:var(--muted)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .sw{width:10px;height:10px;border-radius:3px;display:inline-block}
  .tip{position:absolute;pointer-events:none;background:var(--ink);color:var(--paper);
       font-size:12px;padding:6px 9px;border-radius:8px;opacity:0;transition:opacity .1s;
       white-space:nowrap;z-index:5}
  .hypo{border-left:4px solid var(--clay)}
  .mile{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--clay);
        border-radius:14px;padding:16px 18px;margin:24px 0 0}
  .mile .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
             align-items:baseline}
  .mile .lab{font-size:15px}
  .mile .amt{font-size:20px;letter-spacing:-.01em}
  .bar{height:10px;border-radius:999px;background:var(--line);margin:12px 0 8px;
       overflow:hidden}
  .bar>i{display:block;height:100%;background:var(--clay);border-radius:999px}
  .mile.done{border-left-color:var(--good)}
  .mile.done .bar>i{background:var(--good)}
  .mile .hint{color:var(--muted);font-size:13px;margin:0}
  /* research programme panel: server rendered, readable with no script */
  .prog{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--clay);
        border-radius:14px;padding:16px 18px;margin:24px 0 0}
  .prog h2{margin:0 0 6px}
  .prog .lead{font-size:17px;margin:0 0 6px}
  .exp{border-top:1px solid var(--line);padding:12px 0 4px;margin-top:12px}
  .exp .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
            align-items:baseline}
  .exp .sum{margin:6px 0 0}
  .v{font-size:12px;font-weight:700;letter-spacing:.04em;padding:3px 10px;border-radius:99px;
     border:1.5px solid currentColor;white-space:nowrap}
  .v-pass{color:var(--good)} .v-fail{color:var(--bad)} .v-open{color:var(--clay)}
  ul.crit{list-style:none;padding:0;margin:6px 0 0;font-size:14px}
  ul.crit li{margin:3px 0}
  li.c-passed{color:var(--good)} li.c-failed{color:var(--bad)}
  ul.crit li strong{color:var(--ink);font-weight:600}
  table.meas{max-width:520px}
  .archive{color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.06em;
           text-transform:uppercase;margin:0 0 4px}
  /* family section: first screen, phone sized, plain words */
  .fam{background:var(--card);border:1px solid var(--line);border-radius:16px;
       padding:16px 16px 6px;margin:8px 0 0;font-size:16px}
  .fam p{margin:0 0 10px}
  .fam-intro{font-size:17px}
  .fam-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px;
             margin:4px 0 10px}
  .fam-tile{border:1px solid var(--line);border-radius:12px;padding:10px 10px 8px}
  .fam .fam-q{color:var(--muted);font-size:13px;margin:0 0 2px}
  .fam .fam-n{font-size:22px;font-weight:650;letter-spacing:-.02em;margin:0;line-height:1.2}
  .fam-n small{font-size:14px;font-weight:600}
  .fam-tile.up .fam-n{color:var(--good)} .fam-tile.down .fam-n{color:var(--bad)}
  .fam-halt{border:2px solid var(--bad);color:var(--bad);border-radius:12px;padding:10px 12px;
            font-weight:650}
  .fam-hint{color:var(--muted);font-size:13px}
  h2.more{font-size:16px;margin:28px 0 2px;color:var(--muted)}
  @media (max-width:520px){header{padding:14px 0 2px} h1{font-size:22px}
    .fam{padding:12px 12px 4px;font-size:15px;line-height:1.45} .fam p{margin:0 0 8px}
    .fam-intro{font-size:15px} .fam .fam-n{font-size:19px} .fam-tile{padding:8px 8px 6px}
    .fam-tiles{gap:6px}}
  details.sec{margin-top:10px;border:1px solid var(--line);border-radius:12px;padding:0 14px;
              background:var(--card)}
  details.sec>summary{padding:14px 0;font-size:15px;color:var(--ink);font-weight:600;
                      min-height:44px}
  details.sec[open]{padding-bottom:14px}
  details.sec .viz,details.sec .prog,details.sec .chat{border-left-width:1px}
</style></head><body><div class="wrap">

<!-- FAMILY SECTION. Server rendered, no script needed, written for people who do not trade.
     It must fit on one phone screen. Everything technical is folded away below it. -->
__FAMILY__

<h2 class="more">For Thabang: the detail</h2>
<p class="hint">Tap a heading to open it.</p>

<details class="sec" id="d-numbers">
  <summary>More numbers: money made, lost and at risk</summary>
  <p class="sub" id="asof"></p>
  <div class="mile" id="mile" hidden></div>
  <div class="grid" id="cards"></div>
  <!-- PLAIN FALLBACK for browsers that cannot run the script. The script removes it once it
       has drawn the real cards. -->
  <div id="plain">__PLAIN__</div>
  <div class="banner" id="why"></div>
  <div id="openpos"></div>
</details>

<details class="sec" id="d-charts">
  <summary>Charts: money over time</summary>
  <div class="viz" id="viz-stand">
    <h3>Where your money stands</h3>
    <p class="cap" id="cap-stand"></p>
    <div id="stand"></div>
  </div>
  <div class="viz" id="viz-balance">
    <h3>Your money over time</h3>
    <p class="cap">Real money in the account. Nothing here is a projection.</p>
    <div id="balance"></div>
  </div>
</details>

<details class="sec" id="d-programme">
  <summary>Research experiments: what was tried, what passed and failed</summary>
  <!-- RESEARCH PROGRAMME. Server rendered from the repo files and never touched by the
       script, so it reads the same on a TV with no JavaScript. -->
  __PROGRAMME__
</details>

<details class="sec" id="d-health">
  <summary>Is the system healthy?</summary>
  <div class="viz" id="viz-health">
    <h3>Has the system been working?</h3>
    <p class="cap">One column per day. The system checks itself and cannot mark its own
       homework: a check it could not run counts as a problem.</p>
    <div id="health"></div>
  </div>
</details>

<details class="sec" id="d-archive">
  <summary>Archive of the old daily search</summary>
  <div class="viz hypo" id="viz-ideas">
    <p class="archive">Archive: the old daily search, stopped on 22 September 2026</p>
    <h3>What each idea from the old daily search would have done to your money</h3>
    <p class="cap">This is a record, not live activity. The system used to test ideas every
       day; that stopped on 22 September 2026 and was replaced by the research programme.
       <strong>None of this happened.</strong> Each bar is a test against the same
       past prices the idea was chosen on, so a bar showing a gain is not proof of anything.
       The test that counts is whether the idea still worked on prices it had never seen, and
       that result is written next to each bar. No real money was involved.</p>
    <div id="ideas"></div>
  </div>
  <h3>What it has learned</h3>
  <ul class="lessons" id="lessons"></ul>
</details>

<details class="sec" id="d-goal">
  <summary>Tell it what you want (needs the password)</summary>
  <div class="chat">
    <div id="loginbox" hidden>
      <p class="q">Sign in to set a goal.</p>
      <div class="row">
        <div><input id="pw" type="password" placeholder="Password" autocomplete="current-password"></div>
        <div style="flex:0"><button id="loginbtn">Sign in</button></div>
      </div>
    </div>
    <div id="goalbox" hidden>
      <div class="row"><div>
        <input id="who" placeholder="Your name" autocomplete="name">
      </div></div>
      <textarea id="goal" placeholder="For example: I want to turn this into R2000 by December, and I can afford to lose half."></textarea>
      <button id="send">Ask</button>
      <div class="reply" id="reply" hidden></div>
    </div>
    <p class="hint">This sets a goal for the research system. It cannot place a trade, and
    nothing you type here moves money.</p>
  </div>
</details>

<details class="sec" id="d-tech">
  <summary>Technical table</summary>
  <table id="tech"></table>
</details>

<p class="foot" id="foot"></p>
</div>
<script>
const $=id=>document.getElementById(id);
const money=v=>'R'+Number(v||0).toLocaleString(undefined,{maximumFractionDigits:0});
let D={};
async function load(){
  D=await (await fetch('/api/data')).json();
  // The server-rendered fallback has done its job once the real cards exist.
  var plain=$('plain'); if(plain){ plain.remove(); }
  $('asof').textContent = D.as_of ? ('Balance as of '+new Date(D.as_of).toLocaleString()) :
      'No balance recorded yet.';
  $('cards').innerHTML=[
    ['How much money do I have?', money(D.have_zar), '', 'about $'+Number(D.have_usd||0).toFixed(2)],
    ['How much did it try to trade?', money(D.risked_zar), '',
      D.open_positions&&D.open_positions.length ? 'at risk in '+D.open_positions.length+' open trade(s) if the stop is hit'
        : (D.executed? (D.executed+' trades placed') : 'nothing at risk right now')],
    ['How much did it make?', money(D.made_zar + Math.max(D.unrealised_zar||0,0)),
      (D.made_zar + Math.max(D.unrealised_zar||0,0))>0?'good':'',
      (D.unrealised_zar>0 ? 'includes R'+Number(D.unrealised_zar).toFixed(2)+' not cashed in yet'
                          : 'money actually won')],
    ['How much did it lose?', money(D.lost_zar + Math.max(-(D.unrealised_zar||0),0)),
      (D.lost_zar + Math.max(-(D.unrealised_zar||0),0))>0?'bad':'',
      (D.unrealised_zar<0 ? 'includes R'+Number(-D.unrealised_zar).toFixed(2)+' down on an open trade'
                          : 'money actually lost')],
  ].map(([q,n,cls,h])=>`<div class="card"><p class="q">${q}</p>
      <p class="n ${cls}">${n}</p><p class="hint">${h}</p></div>`).join('');
function renderMilestone(m){
  const box=$('mile');
  if(!m||!m.evaluable){ box.hidden=true; return; }
  box.hidden=false;
  const pct=Math.round((m.progress||0)*100);
  const done=!!m.reached;
  box.className='mile'+(done?' done':'');
  // The status is carried by the WORDS, not by the bar colour: red and green sit about
  // 4 units apart in perceptual difference for a colour-blind reader, so colour alone
  // would not be readable. Same rule as the charts below.
  const head = done
    ? 'Target reached. The next R'+Number(m.unlock_zar).toLocaleString()+' can go in.'
    : 'Next step: earn R'+Number(m.gap_zar).toFixed(2)+' more';
  const hint = done
    ? 'It grew R'+Number(m.baseline_zar).toFixed(2)+' to R'+Number(m.current_zar).toFixed(2)
      +', which is the 1% you asked to see first.'
    : 'You said you would add R'+Number(m.unlock_zar).toLocaleString()+' after seeing '
      +'1% back. That is R'+Number(m.target_zar).toFixed(2)+' in the account, from the '
      +'R'+Number(m.baseline_zar).toFixed(2)+' it started with.';
  box.innerHTML='<div class="top"><span class="lab">'+head+'</span>'
    +'<span class="amt">'+pct+'%</span></div>'
    +'<div class="bar"><i style="width:'+Math.max(pct,1)+'%"></i></div>'
    +'<p class="hint">'+hint+'</p>';
}
  renderMilestone(D.milestone);
  $('why').innerHTML='<strong>What is it doing?</strong><br>'+D.why_no_trade;
  // Open trades, in plain words. Straight from the broker, refreshed hourly.
  $('openpos').innerHTML = (D.open_positions&&D.open_positions.length)
    ? '<div class="banner"><strong>Trade open right now</strong><br>'
      + D.open_positions.map(function(p){
          var up = Number(p.unrealised_usd||0) * D.zar_per_usd;
          var word = up>=0 ? ('up R'+Math.abs(up).toFixed(2)) : ('down R'+Math.abs(up).toFixed(2));
          return 'Bought '+p.volume_lots+' of '+p.symbol+' at '+p.entry_price
            +'. Now '+(p.current_price||'?')+', so it is '+word+'.<br>'
            +(p.take_profit!=null
              ? 'It sells itself at '+p.stop_loss+' to stop the loss, or at '+p.take_profit+' to take the profit.'
              : 'It sells itself at '+p.stop_loss+' to stop the loss, or when the direction changes. There is no profit target.')
            +' Nothing needs to be watching.';
        }).join('<hr>')
      + '</div>'
    : '';
  $('lessons').innerHTML = (D.lessons&&D.lessons.length)
    ? D.lessons.map(l=>`<li>${l.lesson}<div class="ev">${l.evidence||''}</div></li>`).join('')
    : `<li>The old daily search tested ${D.ideas_tested} ideas before it stopped on
       22 September 2026, and none of them beat the cost of trading. That is the finding: the
       easy ideas do not work, which is why research is now a short list of planned
       experiments instead of betting.<div class="ev">From the engine's own test results.</div></li>`;
  $('tech').innerHTML=`<tr><th>Ideas tested by the old daily search (stopped 22 Sep 2026)</th><td>${D.ideas_tested}</td></tr>
    <tr><th>Of those, ideas that passed the bar</th><td>${D.ideas_passed}</td></tr>
    <tr><th>Research orders attempted / executed</th><td>${D.attempted} / ${D.executed}</td></tr>
    <tr><th>Cost-measurement probes</th><td>${D.probes_done}</td></tr>
    <tr><th>Balance (USD)</th><td>${Number(D.have_usd||0).toFixed(2)}</td></tr>
    <tr><th>Rate used</th><td>R${D.zar_per_usd}/USD</td></tr>
    <tr><th>Last run of the old daily search</th><td>${D.last_run||'never'}</td></tr>
    <tr><th>Smallest trade needs</th><td>R${Math.round(D.floor_zar||0)}</td></tr>`
    + (D.outcomes||[]).map(o=>`<tr><th>${o.label}</th><td>${o.pct}% =
        ${o.zar<0?'-':'+'}R${Math.abs(Math.round(o.zar))} on your stake
        (${o.verdict||'?'}), hypothetical, old daily search</td></tr>`).join('');
  drawAll();
  $('foot').textContent = D.configured ? '' : 'Data source not configured yet.';
  $('loginbox').hidden = !!document.cookie.includes('auth=') || !D.can_set_goals;
  $('goalbox').hidden  = !document.cookie.includes('auth=');
  if(!D.can_set_goals){ $('loginbox').hidden=true; $('goalbox').hidden=true;
    $('reply').hidden=false; $('reply').textContent=
      'The goal channel is closed: the dashboard has no write key or no password set.'; }
}
// ---------------------------------------------------------------- charts
// Hand-rolled SVG: no chart library, so the page stays small and there is nothing
// to go stale. Every mark gets a hover tooltip; status is carried by a glyph as well
// as colour, because red and green are 4.1 apart for deuteranopia and colour alone
// would make the health strip unreadable for a colourblind viewer.
const SVGNS='http://www.w3.org/2000/svg';
function el(n,a={}){const e=document.createElementNS(SVGNS,n);
  for(const k in a)e.setAttribute(k,a[k]);return e;}
function tipFor(host){let t=host.querySelector('.tip');
  if(!t){t=document.createElement('div');t.className='tip';host.appendChild(t);}return t;}
function hover(host,node,text){
  const t=tipFor(host);
  node.addEventListener('pointerenter',ev=>{t.textContent=text;t.style.opacity=1;});
  node.addEventListener('pointermove',ev=>{const r=host.getBoundingClientRect();
    t.style.left=(ev.clientX-r.left+12)+'px';t.style.top=(ev.clientY-r.top-34)+'px';});
  node.addEventListener('pointerleave',()=>{t.style.opacity=0;});
}
function empty(id,msg){$(id).innerHTML='<p class="empty">'+msg+'</p>';}

// 1. Where the money stands: one track, three markers. Not a gauge - a position on a line.
function drawStand(){
  const host=$('viz-stand'), now=D.have_zar||0, floor=D.floor_zar||0,
        target=D.goal_target_zar||Math.max(now*2,floor*3);
  const W=720,H=104,L=12,R=12,max=Math.max(target,floor,now)*1.12||1;
  const x=v=>L+(W-L-R)*(v/max);
  const s=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img',
    'aria-label':`Balance R${Math.round(now)}, floor R${Math.round(floor)}, target R${Math.round(target)}`});
  s.appendChild(el('rect',{x:L,y:34,width:W-L-R,height:8,rx:4,fill:'var(--mid)'}));
  // the reachable band: from the floor up to the target
  s.appendChild(el('rect',{x:x(floor),y:34,width:Math.max(x(target)-x(floor),0),height:8,rx:4,
                           fill:'var(--gain)','fill-opacity':.18}));
  const mark=(v,label,color,above,tier)=>{
    const g=el('g'), drop=(tier||0)*16;
    g.appendChild(el('line',{x1:x(v),x2:x(v),y1:above?20:42,y2:above?38:56+drop,
                             stroke:color,'stroke-width':2,'stroke-linecap':'round'}));
    g.appendChild(el('circle',{cx:x(v),cy:38,r:5,fill:color,stroke:'var(--card)','stroke-width':2}));
    const t=el('text',{x:x(v),y:above?14:70+drop,'text-anchor':'middle','font-size':12,
                       fill:'var(--axis)'});
    t.textContent=label; g.appendChild(t); s.appendChild(g);
    hover(host,g,`${label}: R${Math.round(v).toLocaleString()}`);
  };
  // Labels below the track collide when two values are close, so the second one drops
  // to a lower line instead of overprinting the first.
  const below=[[floor,'Smallest trade possible','var(--loss)'],[target,'Goal','var(--gain)']]
    .sort((a,b)=>a[0]-b[0]);
  let lastX=-1e9, tier=0;
  below.forEach(([v,label,color])=>{
    tier = (x(v)-lastX < 150) ? 1-tier : 0;
    mark(v,label,color,false,tier); lastX=x(v);
  });
  mark(now,'You have R'+Math.round(now).toLocaleString(),'var(--line-1)',true,0);
  s.style.maxWidth=W+'px';
  $('stand').innerHTML=''; $('stand').appendChild(s);
  $('cap-stand').textContent = now<floor
    ? `You are below the amount needed to place even the smallest trade, so nothing can be attempted until there is at least R${Math.round(floor).toLocaleString()} in the account.`
    : `There is enough to trade. The goal is R${Math.round(target).toLocaleString()}.`;
}

// 2. Money over time. One reading is not a line, and we say so instead of drawing a stub.
function drawBalance(){
  const host=$('viz-balance'), d=(D.balance_series||[]);
  if(d.length<2){ empty('balance', d.length
      ? 'Only one reading so far, taken '+new Date(d[0].t).toLocaleDateString()+
        '. The line starts once there are two.'
      : 'No readings yet.'); return; }
  const W=720,H=200,P={t:14,r:14,b:26,l:52};
  const xs=d.map(p=>new Date(p.t).getTime()), ys=d.map(p=>p.v);
  const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(0,...ys),y1=Math.max(...ys)*1.08||1;
  const X=v=>P.l+(W-P.l-P.r)*((v-x0)/((x1-x0)||1));
  const Y=v=>H-P.b-(H-P.t-P.b)*((v-y0)/((y1-y0)||1));
  const s=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Balance over time'});
  for(let i=0;i<=3;i++){ const v=y0+(y1-y0)*i/3;
    s.appendChild(el('line',{x1:P.l,x2:W-P.r,y1:Y(v),y2:Y(v),stroke:'var(--grid)','stroke-width':1}));
    const t=el('text',{x:P.l-8,y:Y(v)+4,'text-anchor':'end','font-size':11,fill:'var(--axis)'});
    t.textContent='R'+Math.round(v).toLocaleString(); s.appendChild(t); }
  s.appendChild(el('path',{d:d.map((p,i)=>(i?'L':'M')+X(new Date(p.t).getTime())+' '+Y(p.v)).join(' '),
    fill:'none',stroke:'var(--line-1)','stroke-width':2,'stroke-linejoin':'round','stroke-linecap':'round'}));
  d.forEach(p=>{const c=el('circle',{cx:X(new Date(p.t).getTime()),cy:Y(p.v),r:4,
      fill:'var(--line-1)',stroke:'var(--card)','stroke-width':2});
    const hit=el('circle',{cx:X(new Date(p.t).getTime()),cy:Y(p.v),r:12,fill:'transparent'});
    s.appendChild(c); s.appendChild(hit);
    hover(host,hit,new Date(p.t).toLocaleDateString()+': R'+Math.round(p.v).toLocaleString());});
  s.style.maxWidth=W+'px';
  $('balance').innerHTML=''; $('balance').appendChild(s);
}

// 3. Health strip. Status carries a GLYPH as well as colour - never colour alone.
const GLYPH={PASS:'✓',UNKNOWN:'?',FAIL:'✕'};
const SCOL={PASS:'var(--ok)',UNKNOWN:'var(--unknown)',FAIL:'var(--bad)'};
const SNAME={PASS:'Fine',UNKNOWN:'Could not tell',FAIL:'A problem'};
function drawHealth(){
  const host=$('viz-health'), g=D.audit_grid||{days:[],checks:[],cells:[]};
  if(!g.days.length){ empty('health','The system has not checked itself yet.'); return; }
  const cw=Math.min(30,Math.max(16,620/g.days.length)), rh=26, L=210;
  const W=L+g.days.length*cw+10, H=g.checks.length*rh+24;
  const s=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'System health by day'});
  g.checks.forEach((cid,r)=>{
    const t=el('text',{x:0,y:r*rh+rh/2+4+18,'font-size':12,fill:'var(--axis)'});
    t.textContent=cid.replace(/_/g,' ').slice(0,30); s.appendChild(t);
    g.cells[r].forEach((st,c)=>{
      if(!st) return;
      const X=L+c*cw, Y=r*rh+18;
      // 2px gap between cells so adjacent fills never touch
      const cell=el('rect',{x:X+1,y:Y+1,width:cw-3,height:rh-5,rx:4,fill:SCOL[st],
                            'fill-opacity':.22,stroke:SCOL[st],'stroke-width':1.5});
      const gl=el('text',{x:X+(cw-2)/2,y:Y+rh/2+3,'text-anchor':'middle','font-size':12,
                          fill:'var(--ink)'});
      gl.textContent=GLYPH[st]||'';
      s.appendChild(cell); s.appendChild(gl);
      hover(host,cell,`${g.days[c]} - ${cid.replace(/_/g,' ')}: ${SNAME[st]}`);
    });
  });
  s.style.maxWidth=W+'px';
  $('health').innerHTML=''; $('health').appendChild(s);
  $('health').insertAdjacentHTML('beforeend','<div class="legend">'+
    Object.keys(GLYPH).map(k=>`<span><span class="sw" style="background:${SCOL[k]}"></span>`+
      `${GLYPH[k]} ${SNAME[k]}</span>`).join('')+'</div>');
}

// 4. What each idea would have done. Diverging around zero: gained one side, lost the other.
function drawIdeas(){
  const host=$('viz-ideas'), d=(D.outcomes||[]);
  if(!d.length){ empty('ideas','No ideas have been tested yet.'); return; }
  const rh=24, L=150, W=720, H=d.length*rh+30, mid=L+(W-L-70)/2;
  const max=Math.max(...d.map(o=>Math.abs(o.zar)),1);
  const half=(W-L-70)/2;
  const s=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Hypothetical outcome per idea'});
  s.appendChild(el('line',{x1:mid,x2:mid,y1:14,y2:H-16,stroke:'var(--grid)','stroke-width':1}));
  d.forEach((o,i)=>{
    const y=i*rh+18, w=Math.max(Math.abs(o.zar)/max*half,2), gain=o.zar>=0;
    const t=el('text',{x:0,y:y+13,'font-size':12,fill:'var(--axis)'});
    t.textContent=o.label.slice(0,22); s.appendChild(t);
    // 4px rounded data-end, anchored to the zero baseline
    const bar=el('rect',{x:gain?mid:mid-w,y:y+3,width:w,height:rh-9,rx:4,
                         fill:gain?'var(--gain)':'var(--loss)'});
    s.appendChild(bar);
    // A long bar's value goes INSIDE it; outside it would overprint the row label.
    const inside=w>46;
    const v=el('text',{x:gain?(inside?mid+w-6:mid+w+6):(inside?mid-w+6:mid-w-6),y:y+14,
                       'font-size':11,'text-anchor':gain?(inside?'end':'start'):(inside?'start':'end'),
                       fill:inside?'var(--card)':'var(--muted)'});
    v.textContent=(gain?'+':'-')+'R'+Math.abs(Math.round(o.zar)).toLocaleString();
    s.appendChild(v);
    // The verdict on UNSEEN prices, beside the bar. Without it a long blue bar reads as a
    // win, when every one of these ideas was rejected.
    const tagText = o.verdict==='PASS' ? 'passed'
                  : (o.held_up===true ? 'failed (held up, but could be luck)'
                  : (o.held_up===false ? 'failed on unseen prices' : 'failed'));
    const tag=el('text',{x:W-2,y:y+14,'font-size':10,'text-anchor':'end',
                         fill:o.verdict==='PASS'?'var(--gain)':'var(--muted)'});
    tag.textContent=tagText; s.appendChild(tag);
    hover(host,bar,`${o.label}: ${gain?'would have gained':'would have lost'} R`+
      `${Math.abs(Math.round(o.zar)).toLocaleString()} (${o.pct}%) - ${tagText}`);
  });
  s.style.maxWidth=W+'px';
  $('ideas').innerHTML=''; $('ideas').appendChild(s);
  const lost=d.filter(o=>o.zar<0).length;
  const passed=D.outcomes_passed||0;
  $('ideas').insertAdjacentHTML('beforeend','<div class="legend">'+
    `<span><span class="sw" style="background:var(--loss)"></span>Would have lost money</span>`+
    `<span><span class="sw" style="background:var(--gain)"></span>Would have made money</span>`+
    `<span>${lost} of ${d.length} lost money on the prices they were picked on, `+
    `and ${passed} of ${d.length} passed the test that decides.</span></div>`);
}

// The charts are inline SVG with a viewBox, so they scale to whatever width their box has
// and draw correctly inside a closed <details>. They are redrawn when a block is opened anyway,
// so nothing depends on the size the box had while it was folded away.
function drawAll(){
  [drawStand,drawBalance,drawHealth,drawIdeas].forEach(function(f){
    try{ f(); }catch(e){ if(window.console) console.error(e); } });
}
document.querySelectorAll('details').forEach(function(d){
  d.addEventListener('toggle',function(){ if(d.open && D && D.audit_grid){ drawAll(); } });
});
$('loginbtn').onclick=async()=>{
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:$('pw').value})});
  if(r.ok){ $('loginbox').hidden=true; $('goalbox').hidden=false; }
  else { $('pw').value=''; $('pw').placeholder='Wrong password'; }
};
$('send').onclick=async()=>{
  const b=$('send'); b.disabled=true; b.textContent='Working it out…';
  const r=await fetch('/api/goal',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:$('goal').value,author:$('who').value})});
  const j=await r.json();
  $('reply').hidden=false; $('reply').textContent=j.reply||j.error||'Something went wrong.';
  b.disabled=false; b.textContent='Ask';
};
load();
</script></body></html>
"""


# ---------------------------------------------------------------- research programme
# Since 2026-09-22 research is a budget of ten pre-registered experiments, recorded in
# docs/programme/register.json with results in docs/results/. The panel reads those files at
# request time (the service runs from a checkout of the repo) and renders on the server, so
# it shows on a TV with no JavaScript. A missing or broken file gives a plain note, never an
# error page.
REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER_PATH = "docs/programme/register.json"

# Plain words for the pass criteria we know about. Anything else is shown by its own name.
CRITERIA_WORDS = {
    "C1_net_sharpe_positive": "Made money after trading costs",
    "C2_beats_null_p95": "Did better than random guessing",
    "C3_years_and_last_12m": "Made money in most years, and in the last 12 months",
    "C4_survives_double_costs": "Still made money with trading costs doubled",
}
MEASURE_WORDS = {
    "n_probes": "Test trades measured",
    "mean_adverse_slippage_pips": "Average slippage against us (pips)",
    "p95_adverse_slippage_pips": "Slippage on the worst 1 in 20 trades (pips)",
    "mean_latency_ms": "Average time for the broker to respond (milliseconds)",
    "verdict": "Verdict",
}


def _words(key: str, known: dict) -> str:
    if key in known:
        return known[key]
    k = re.sub(r"^C\d+_", "", str(key)).replace("_", " ").strip()
    return k[:1].upper() + k[1:] if k else str(key)


def _read_json(path: Path) -> tuple[dict | None, str]:
    """(data, note). Data is None when the file is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, "missing"
    except Exception as exc:                      # noqa: BLE001
        return None, f"unreadable ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, "unreadable (not a JSON object)"
    return data, ""


def _result_json_path(exp: dict, root: Path) -> Path | None:
    """The result's JSON twin: the register names the .md write-up, the numbers sit beside it."""
    res = exp.get("result")
    if isinstance(res, str) and res:
        p = root / res
        return p if p.suffix == ".json" else p.with_suffix(".json")
    eid = str(exp.get("id") or "")
    if eid:
        hits = sorted((root / "docs" / "results").glob(f"{eid}-*.json"))
        if hits:
            return hits[0]
    return None


def _sentence(reg: dict, root: Path) -> str:
    """The programme's own plain sentence, with a local fallback if that module will not load."""
    try:
        from research.programme import status
        return status(reg, repo=str(root), check_git=False).sentence()
    except Exception:                             # noqa: BLE001
        exps = [e for e in reg.get("experiments", []) if isinstance(e, dict)]
        done = [e for e in exps if e.get("verdict") in ("PASS", "FAIL")]
        passed = [e for e in done if e.get("verdict") == "PASS"]
        return (f"So far {len(done)} of {reg.get('budget', '?')} experiments are done and "
                f"{len(passed)} passed.")


def _programme_data(root: Path | str | None = None) -> dict:
    """Everything the programme panel shows, read from the repo files. Never raises."""
    try:
        return _programme_data_unsafe(Path(root) if root else REPO_ROOT)
    except Exception as exc:                      # noqa: BLE001
        return {"ok": False, "note": f"The research programme could not be read "
                                     f"({type(exc).__name__})."}


def _programme_data_unsafe(root: Path) -> dict:
    reg, why = _read_json(root / REGISTER_PATH)
    if reg is None:
        return {"ok": False, "note": f"The experiment register is {why}, so the research "
                                     f"programme cannot be shown right now."}
    progs = reg.get("programmes") if isinstance(reg.get("programmes"), list) else None
    current = progs[-1] if progs and isinstance(progs[-1], dict) else {"id": "P1"}
    first = progs[0].get("id", "P1") if progs and isinstance(progs[0], dict) else "P1"
    try:
        budget = int(current.get("budget") or reg.get("budget") or 0)
    except (TypeError, ValueError):
        budget = 0
    raw = reg.get("experiments")
    exps = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    rows = []
    for e in exps:
        verdict = e.get("verdict")
        verdict = verdict.upper() if isinstance(verdict, str) else None
        row = {"id": str(e.get("id") or "?"), "title": str(e.get("title") or ""),
               "verdict": verdict if verdict in ("PASS", "FAIL") else "IN PROGRESS",
               "summary": str(e.get("summary") or ""), "criteria": [], "measurements": [],
               "note": "",
               # Slots are counted for the current programme only; audits spend none.
               "counts": (e.get("programme", first) == current.get("id", "P1")
                          and e.get("kind") != "audit")}
        path = _result_json_path(e, root)
        if path is not None:
            data, why = _read_json(path)
            if data is None:
                # An experiment still running has no result yet; that is not a problem.
                if why != "missing" or row["verdict"] != "IN PROGRESS":
                    row["note"] = f"The detailed result file is {why}."
            else:
                crit = data.get("criteria")
                if isinstance(crit, dict):
                    row["criteria"] = [{"key": str(k), "words": _words(k, CRITERIA_WORDS),
                                        "passed": v is True} for k, v in crit.items()]
                meas = data.get("measurements")
                if isinstance(meas, dict):
                    row["measurements"] = [{"key": str(k), "words": _words(k, MEASURE_WORDS),
                                            "value": v} for k, v in meas.items()
                                           if not isinstance(v, (dict, list))]
        rows.append(row)
    spent = sum(1 for r in rows if r["counts"] and r["verdict"] in ("PASS", "FAIL"))
    return {"ok": True, "note": "", "sentence": _sentence(reg, root), "budget": budget,
            "spent": spent,
            "passed": sum(1 for r in rows if r["counts"] and r["verdict"] == "PASS"),
            "used_pct": (min(100, round(100 * spent / budget)) if budget > 0 else 0),
            "started": str(reg.get("started") or ""), "experiments": rows}


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "not measured yet" if v is None else str(v)


def _programme_html(p: dict | None = None) -> str:
    """The panel as static HTML. No script is needed to read it."""
    esc = html.escape
    head = "<section class='prog' id='programme'><h2>Research programme</h2>"
    try:
        p = p if p is not None else _programme_data()
        if not p.get("ok"):
            return f"{head}<p class='hint'>{esc(p.get('note', ''))}</p></section>"
        out = [head, f"<p class='lead'>{esc(p['sentence'])}</p>",
               f"<p class='hint'>Instead of trying new ideas every day, the system now gets "
               f"{p['budget']} carefully planned experiments. Each plan is written down and "
               f"saved before it runs, so the result cannot be bent to fit afterwards. Since "
               f"23 September 2026 the best idea that passed trades real money on its own, "
               f"inside fixed safety limits.</p>",
               f"<div class='bar' role='img' aria-label='{p['spent']} of {p['budget']} "
               f"experiments used'><i style='width:{max(p['used_pct'], 1)}%'></i></div>",
               f"<p class='hint'>{p['spent']} of {p['budget']} experiments used.</p>"]
        if not p["experiments"]:
            out.append("<p class='hint'>No experiments have been registered yet.</p>")
        for r in p["experiments"]:
            cls = {"PASS": "pass", "FAIL": "fail"}.get(r["verdict"], "open")
            out.append(f"<div class='exp'><div class='top'><span><strong>{esc(r['id'])}</strong> "
                       f"{esc(r['title'])}</span><span class='v v-{cls}'>{r['verdict']}</span>"
                       f"</div>")
            if r["summary"]:
                out.append(f"<p class='sum'>{esc(r['summary'])}</p>")
            if r["criteria"]:
                n_ok = sum(1 for c in r["criteria"] if c["passed"])
                out.append(f"<p class='hint'>It passed {n_ok} of the {len(r['criteria'])} "
                           f"tests it had to pass:</p><ul class='crit'>")
                for c in r["criteria"]:
                    word = "passed" if c["passed"] else "failed"
                    mark = "&#10003;" if c["passed"] else "&#10005;"
                    out.append(f"<li class='c-{word}'>{mark} {esc(c['words'])}: "
                               f"<strong>{word}</strong></li>")
                out.append("</ul>")
            if r["measurements"]:
                out.append("<table class='meas'>")
                for m in r["measurements"]:
                    out.append(f"<tr><th>{esc(m['words'])}</th>"
                               f"<td>{esc(_fmt(m['value']))}</td></tr>")
                out.append("</table>")
            if r["note"]:
                out.append(f"<p class='hint'>{esc(r['note'])}</p>")
            out.append("</div>")
        out.append("</section>")
        return "".join(out)
    except Exception as exc:                      # noqa: BLE001
        return (f"{head}<p class='hint'>The research programme could not be shown "
                f"({esc(type(exc).__name__)}).</p></section>")


def _safe_data() -> tuple[dict | None, str]:
    """(data, error name). One Supabase read per page, shared by every server-rendered part."""
    try:
        return _dashboard_data(), ""
    except Exception as exc:                      # noqa: BLE001
        return None, type(exc).__name__


def _family_block(d: dict | None) -> str:
    try:
        fam = (d or {}).get("family") or _family(None, [])
        return _family_html(fam)
    except Exception as exc:                      # noqa: BLE001
        return (f"<section class='fam' id='family'><p class='fam-intro'>"
                f"{html.escape(FAMILY_INTRO)}</p><p>The latest numbers could not be loaded "
                f"right now ({type(exc).__name__}). Please refresh in a few minutes.</p>"
                f"</section>")


def _story_block(d: dict | None) -> str:
    """The story on top; the plain family section if anything in it cannot be drawn."""
    if d is None or not (d.get("family") or {}).get("known"):
        return _family_block(d)
    try:
        reg, _ = _read_json(REPO_ROOT / REGISTER_PATH)
        scores = _sb("forecast_scores", "select=hour_utc,player,ic,hit_rate,paper_trades,paper_net_bps"
                     "&order=hour_utc.desc&limit=5000")
        chain = (_sb("forecast_chain", "select=n_lines,head_sha256,published_at&order=id.desc&limit=1")
                 or [None])[0]
        return story_html(d, _programme_data(), reg or {}, read_universe(REPO_ROOT), scores, chain)
    except Exception:                             # noqa: BLE001
        return _family_block(d)


def _plain_fallback(d: dict | None = None, err: str = "") -> str:
    """The four headline numbers as static HTML, for browsers that cannot run the page."""
    if d is None:
        d, err = _safe_data()
    if d is None:
        return (f"<p class='hint'>The live numbers could not be loaded "
                f"({err}). The page will retry when you refresh.</p>")
    rows = [("How much money do I have?", _money(d["have_zar"])),
            ("At risk in open trades", _money(d.get("risked_zar", 0.0))),
            ("Made so far", _money(d.get("made_zar", 0.0))),
            ("Lost so far", _money(d.get("lost_zar", 0.0)))]
    items = "".join(f"<div class='card'><p class='q'>{q}</p><p class='n'>{v}</p></div>"
                    for q, v in rows)
    open_line = ""
    for pos in (d.get("open_positions") or [])[:3]:
        exits = (f"{pos.get('stop_loss')} or {pos['take_profit']}"
                 if pos.get("take_profit") is not None else
                 f"{pos.get('stop_loss')}, or when the direction changes")
        open_line += (f"<p><strong>Trade open:</strong> {(pos.get('side') or '').lower()} "
                      f"{pos.get('symbol')} opened at {pos.get('entry_price')}, now "
                      f"{pos.get('current_price') or '?'}. It sells itself at {exits}.</p>")
    return (f"<div class='grid'>{items}</div>{open_line}"
            f"<p class='hint'>{d.get('why_no_trade','')}</p>")


PLAIN_CSS = ("body{font-family:system-ui,Arial,sans-serif;background:#111;color:#eee;"
             "padding:16px;font-size:20px;max-width:900px;margin:0 auto}"
             ".card{border:1px solid #444;border-radius:12px;"
             "padding:16px;margin:12px 0}.q{color:#aaa;margin:0 0 6px}.n{font-size:34px;"
             "margin:0}.hint{color:#aaa}"
             ".bar{height:10px;border-radius:999px;background:#333;overflow:hidden;"
             "margin:10px 0}.bar>i{display:block;height:100%;background:#c2683f}"
             ".exp{border:1px solid #444;border-radius:12px;padding:14px 16px;margin:12px 0}"
             ".v{font-weight:700;margin-left:8px}.v-pass{color:#6fbf91}.v-fail{color:#e08370}"
             ".v-open{color:#fab219}.crit{padding-left:20px}"
             ".fam{border:1px solid #444;border-radius:14px;padding:14px 16px 4px}"
             ".fam p{margin:0 0 12px}.fam-tiles{display:flex;flex-wrap:wrap;gap:10px;"
             "margin-bottom:12px}.fam-tile{flex:1;min-width:120px;border:1px solid #444;"
             "border-radius:12px;padding:10px 12px}.fam-q{color:#aaa;font-size:16px;"
             "margin:0 0 2px!important}.fam-n{font-size:28px;font-weight:700;margin:0!important}"
             ".fam-n small{font-size:18px}.up .fam-n{color:#6fbf91}.down .fam-n{color:#e08370}"
             ".fam-halt{border:2px solid #e08370;color:#e08370;border-radius:12px;"
             "padding:10px 12px;font-weight:700}.fam-hint{color:#aaa;font-size:17px}"
             "details{border:1px solid #444;border-radius:12px;padding:0 14px;margin:12px 0}"
             "summary{padding:14px 0;cursor:pointer;font-weight:600}")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    """Keep-awake ping. Touches nothing: no Supabase, no files, no model."""
    return "ok"


@app.get("/plain", response_class=HTMLResponse)
def plain() -> str:
    """A page with no JavaScript at all, for a TV or a very old browser."""
    d, err = _safe_data()
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Trading experiment, plain view</title>"
            f"<style>{PLAIN_CSS}</style></head><body>"
            "<h1>Thabang's trading experiment</h1>" + _family_block(d) +
            "<h2>For Thabang: the detail</h2>"
            "<details><summary>More numbers: money made, lost and at risk</summary>"
            + _plain_fallback(d, err) + "</details>"
            "<details><summary>Research experiments: what was tried, what passed and "
            "failed</summary>" + _programme_html() + "</details>"
            "<p class='hint'>This is the simple view. The full page with charts is at /"
            "</p></body></html>")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # The decorator belongs here. From 63ab960 until this fix it sat on _plain_fallback, so
    # "/" served only the bare fallback fragment and never the full page.
    d, err = _safe_data()
    return (PAGE.replace("__FAMILY__", _story_block(d))
                .replace("__PLAIN__", _plain_fallback(d, err))
                .replace("__PROGRAMME__", _programme_html()))
