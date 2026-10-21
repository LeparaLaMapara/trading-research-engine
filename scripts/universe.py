"""What can this account trade at the broker's smallest size? Writes docs/results/universe.json.

Read-only. For every symbol in data/swaps.json: the smallest trade the broker allows, what a
normal stop (2 x the 20-day average daily move) would lose at that size, the overnight fee per
year as a % of the position, and the spread paid per round trip. A symbol "fits" when that
stop loss is within the engine's 6% risk per trade. The dashboard reads the file; it never
needs the price database.

    python -m scripts.universe --db data/market.db --balance 79.45
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RISK = 0.06
BALANCES = (150, 250, 500, 1000)

INDEX_CCY = {"US500": "USD", "US30": "USD", "USTEC": "USD", "US2000": "USD", "DE40": "EUR",
             "F40": "EUR", "STOXX50": "EUR", "ES35": "EUR", "IT40": "EUR", "UK100": "GBP",
             "JP225": "JPY", "HK50": "HKD", "AUS200": "AUD", "CHINA50": "USD", "SA40": "ZAR",
             "SMI": "CHF", "CA60": "CAD"}
CRYPTO = ("BTC", "ETH", "ADA", "SOL", "XRP", "LTC", "BCH", "DOT")
DIRECT = {"EUR": "EURUSD", "GBP": "GBPUSD", "AUD": "AUDUSD", "NZD": "NZDUSD"}
INVERSE = {c: f"USD{c}" for c in ("JPY", "CAD", "CHF", "ZAR", "MXN", "NOK", "SEK", "SGD", "PLN")}


def kind(s: str) -> str:
    if s in INDEX_CCY:
        return "index"
    if s.startswith(("XAU", "XAG", "XPT", "XPD")):
        return "metal"
    if s in ("XTIUSD", "XBRUSD", "XNGUSD"):
        return "energy"
    if s.endswith("USD") and s[:-3] in CRYPTO:
        return "crypto"
    return "currency"


def risk_band(stop_loss_usd: float, balance: float) -> dict:
    """Risk of one minimum-size trade with a 2-ATR stop, as % of equity, and its band."""
    pct = 100.0 * stop_loss_usd / balance if balance > 0 else float("inf")
    band = ("under 1%" if pct < 1 else "1-2%" if pct <= 2 else
            f"2-{RISK * 100:.0f}%" if pct <= RISK * 100 else "too big")
    return {"risk_pct_at_min": round(pct, 2), "risk_band": band,
            "equity_for_2pct_usd": round(stop_loss_usd / 0.02, 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "market.db"))
    ap.add_argument("--balance", type=float, default=79.45)
    ap.add_argument("--out", default=str(ROOT / "docs" / "results" / "universe.json"))
    a = ap.parse_args()

    swaps = json.loads((ROOT / "data" / "swaps.json").read_text(encoding="utf-8"))
    spreads = json.loads((ROOT / "data" / "spread_summary.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)

    def bars(sym: str, n: int) -> list[tuple]:
        rows = db.execute("select high, low, close from bars where symbol=? and period='D1' "
                          "order by ts_utc desc limit ?", (sym, n)).fetchall()
        return rows[::-1]

    def last(sym: str) -> float | None:
        b = bars(sym, 1)
        return b[-1][2] if b else None

    def atr(sym: str, n: int = 20) -> float | None:
        b = bars(sym, n + 1)
        if len(b) < n + 1:
            return None
        trs = [max(h - lo, abs(h - b[i - 1][2]), abs(lo - b[i - 1][2]))
               for i, (h, lo, _) in enumerate(b) if i > 0]
        return sum(trs) / n

    def usd_per(cur: str) -> float | None:
        if cur == "USD":
            return 1.0
        if cur == "HKD":
            return 1 / 7.8                       # pegged
        if cur in DIRECT:
            return last(DIRECT[cur])
        p = last(INVERSE[cur]) if cur in INVERSE else None
        return 1 / p if p else None

    rows = []
    for s, v in sorted(swaps.items()):
        ccy = INDEX_CCY.get(s) or s[-3:]
        px, rng, conv = last(s), atr(s), usd_per(ccy)
        if not (px and rng and conv):
            rows.append({"symbol": s, "kind": kind(s), "priced": False})
            continue
        units = v["minVolume"] / 100
        pip = 10 ** -v["pipPosition"]
        if v["swapCalculationType"] == 1:        # already % per year
            fee_long, fee_short = v["swapLong"], v["swapShort"]
        else:                                    # pips per night, annualised as % of price
            fee_long = v["swapLong"] * pip * 365 / px * 100
            fee_short = v["swapShort"] * pip * 365 / px * 100
        sp = (spreads.get(s) or {}).get("spread_pips")
        rows.append({"symbol": s, "kind": kind(s), "priced": True, "min_units": units,
                     "position_usd": round(px * units * conv, 2),
                     "day_move_pct": round(rng / px * 100, 2),
                     "stop_loss_usd": round(2 * rng * units * conv, 2),
                     "fee_long_pct_yr": round(fee_long, 1),
                     "fee_short_pct_yr": round(fee_short, 1),
                     "spread_usd": None if sp is None else round(sp * pip * units * conv, 3)})

    priced = [r for r in rows if r["priced"]]
    # Design rule 6 (2026-10-21): prefer instruments where the minimum lot at a sane stop risks
    # 1 to 2% of equity; the signed limit (6%) is the ceiling, not the target.
    for r in priced:
        r.update(risk_band(r["stop_loss_usd"], a.balance))
    fits = {str(b): sum(1 for r in priced if r["stop_loss_usd"] <= b * RISK) for b in (a.balance, *BALANCES)}
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "balance_usd": a.balance, "risk_per_trade": RISK, "symbols": len(rows),
           "fits_at": fits,
           "fits_now": [r["symbol"] for r in priced if r["stop_loss_usd"] <= a.balance * RISK],
           "preferred_now": [r["symbol"] for r in priced if r["risk_band"] == "1-2%"],
           "rows": rows}
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out['fits_now'])} of {len(rows)} fit at ${a.balance}: {out['fits_now']}")
    print("fits at:", fits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
