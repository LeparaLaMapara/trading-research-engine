"""Is each live rule still the rule its backtest described? A daily check with written rules.

A backtest is a promise about costs and behaviour. This compares what the account actually
sees against that promise, for every instrument the engine trades live:

  cost       the round-trip cost measured from recorded quotes (median spread in the hours the
             rule may trade, plus commission) against the cost the backtest assumed.
  frequency  how often the live rule opens a trade against how often it did in the backtest.

The rules are fixed here, before the data arrives, so they cannot be bent to fit it:

  * Cost is judged only with at least MIN_TICKS quotes spread over at least MIN_HOURS distinct
    UTC hours of the trading window. Fewer is "not enough data", never a verdict.
  * Measured cost above the assumed cost is a WARNING: the backtest was optimistic.
  * Measured cost above twice the assumed cost PAUSES new entries on that instrument. Every
    live rule was required to survive doubled costs; beyond that the evidence for it is gone.
    A pause never closes an open position (its stop still protects it) and is lifted by
    deleting `paused:<SYMBOL>` from data/engine_state.json once a re-scored test passes.
  * Frequency is reported, not acted on, until the rule has run for FREQ_MIN_DAYS.

    python -m research.live_check          # writes docs/results/live-check.{md,json}
"""
from __future__ import annotations

import calendar
import json
import sqlite3
import statistics
import time

TELEMETRY = "data/telemetry.db"
DECISIONS = "data/engine_decisions.jsonl"
STATE = "data/engine_state.json"
OUT = "docs/results/live-check"
COMMISSION_SIDE = 0.000035          # the same figure every experiment used
WINDOW_DAYS = 14
MIN_TICKS = 300
MIN_HOURS = 5
FREQ_MIN_DAYS = 60

#: symbol -> where its backtest lives, and the UTC hours it may not trade.
LIVE = {
    # E07's JSON did not record its cost; it used E05's cost mechanics, and E05's result
    # (docs/results/E05-eth-trend.md) states 11.9 bps per round trip.
    "ETHUSD": {"experiment": "E07", "result": "docs/results/E07-no-target.json", "pair": None,
               "blackout": None, "assumed_cost_bps": 11.9},
    "USDSGD": {"experiment": "E08", "result": "docs/results/E08-fx-trend.json",
               "pair": "USDSGD", "blackout": (20, 23)},
}


def backtest_facts(spec: dict) -> dict:
    with open(spec["result"], encoding="utf-8") as fh:
        res = json.load(fh)
    stats = res["pairs"][spec["pair"]] if spec["pair"] else res
    years = stats["days"] / 365.25
    return {"assumed_cost_bps": stats.get("cost_round_trip_bps") or spec.get("assumed_cost_bps"),
            "trades_per_year": round(stats["round_trips"] / years, 1) if years else None,
            "net_sharpe": stats.get("net_sharpe"),
            "net_sharpe_double_costs": stats.get("net_sharpe_double_costs")}


def measured_cost(symbol: str, blackout, now: float, db: str = TELEMETRY) -> dict:
    """Median round-trip cost in bps over the recent window, outside the blackout hours."""
    since = now - WINDOW_DAYS * 86400
    try:
        with sqlite3.connect(db) as c:
            rows = c.execute("SELECT ts_utc, bid, ask FROM ticks WHERE symbol=? AND ts_utc>=? "
                             "AND bid>0 AND ask>=bid", (symbol, since)).fetchall()
    except sqlite3.Error as exc:
        return {"error": str(exc), "ticks": 0, "hours": 0}
    costs, hours = [], set()
    for ts, bid, ask in rows:
        h = time.gmtime(ts).tm_hour
        if blackout and blackout[0] <= h < blackout[1]:
            continue
        costs.append((ask - bid) / ((ask + bid) / 2) + 2 * COMMISSION_SIDE)
        hours.add(h)
    if not costs:
        return {"ticks": 0, "hours": 0}
    return {"ticks": len(costs), "hours": len(hours),
            "median_cost_bps": round(statistics.median(costs) * 1e4, 2),
            "p90_cost_bps": round(sorted(costs)[int(0.9 * (len(costs) - 1))] * 1e4, 2)}


def live_opens(symbol: str, path: str = DECISIONS) -> list[float]:
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            sym = d.get("symbol", "ETHUSD")
            if sym == symbol and d.get("action") == "open":
                out.append(calendar.timegm(time.strptime(d["ts"], "%Y-%m-%dT%H:%M:%SZ")))
    except OSError:
        pass
    return out


def cost_verdict(measured: dict, assumed_bps: float | None) -> tuple[str, str]:
    """The written rule. Returns (status, reason); status is OK, WARN, PAUSE or NO-DATA."""
    if not assumed_bps:
        return "NO-DATA", "the backtest did not record its assumed cost"
    if measured.get("ticks", 0) < MIN_TICKS or measured.get("hours", 0) < MIN_HOURS:
        return "NO-DATA", (f"{measured.get('ticks', 0)} quotes over {measured.get('hours', 0)} "
                           f"hours; need {MIN_TICKS} over {MIN_HOURS}")
    m = measured["median_cost_bps"]
    if m > 2 * assumed_bps:
        return "PAUSE", (f"measured {m:.2f} bps is more than twice the {assumed_bps:.2f} bps "
                         f"the backtest assumed")
    if m > assumed_bps:
        return "WARN", f"measured {m:.2f} bps is above the assumed {assumed_bps:.2f} bps"
    return "OK", f"measured {m:.2f} bps is within the assumed {assumed_bps:.2f} bps"


def check(now: float | None = None) -> dict:
    now = now or time.time()
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "rules": {}}
    for sym, spec in LIVE.items():
        bt = backtest_facts(spec)
        mc = measured_cost(sym, spec["blackout"], now)
        status, why = cost_verdict(mc, bt["assumed_cost_bps"])
        opens = live_opens(sym)
        days_live = (now - min(opens)) / 86400 if opens else 0.0
        freq = {"live_opens": len(opens), "days_live": round(days_live, 1),
                "expected_opens": round(bt["trades_per_year"] * days_live / 365.25, 1)
                if bt["trades_per_year"] else None,
                "judged": days_live >= FREQ_MIN_DAYS}
        report["rules"][sym] = {"experiment": spec["experiment"], "backtest": bt,
                                "measured": mc, "cost_status": status, "cost_reason": why,
                                "frequency": freq}
    return report


def apply_pauses(report: dict, path: str = STATE) -> list[str]:
    """Write `paused:<SYMBOL>` for every PAUSE verdict. Never removes a pause."""
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    added = []
    for sym, r in report["rules"].items():
        key = f"paused:{sym}"
        if r["cost_status"] == "PAUSE" and key not in st:
            st[key] = f"{report['ts']}: {r['cost_reason']}"
            added.append(sym)
    if added:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1)
    return added


def render(report: dict) -> str:
    L = ["# Live check: are the live rules still the rules their backtests described?", "",
         f"Written {report['ts']} by `research/live_check.py`. The rules are in that file's "
         "docstring and were fixed before any live data arrived.", "",
         "| instrument | test | assumed cost | measured cost (median, p90) | quotes, hours | "
         "cost | live opens vs backtest pace |", "|---|---|---|---|---|---|---|"]
    for sym, r in report["rules"].items():
        bt, mc, fq = r["backtest"], r["measured"], r["frequency"]
        cost = (f"{mc['median_cost_bps']}, {mc['p90_cost_bps']} bps"
                if "median_cost_bps" in mc else "none yet")
        pace = (f"{fq['live_opens']} in {fq['days_live']} days vs {fq['expected_opens']}"
                + ("" if fq["judged"] else " (too early to judge)"))
        L.append(f"| {sym} | {r['experiment']} | {bt['assumed_cost_bps'] or 'not recorded'} "
                 f"bps | {cost} | {mc.get('ticks', 0)}, {mc.get('hours', 0)} | "
                 f"**{r['cost_status']}** | {pace} |")
    L += ["", "Reasons:", ""] + [f"* {s}: {r['cost_reason']}" for s, r in
                                 report["rules"].items()]
    return "\n".join(L) + "\n"


def main() -> int:
    report = check()
    report["paused_now"] = apply_pauses(report)
    with open(f"{OUT}.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    with open(f"{OUT}.md", "w", encoding="utf-8") as fh:
        fh.write(render(report))
    for sym, r in report["rules"].items():
        print(f"{sym}: {r['cost_status']} ({r['cost_reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
