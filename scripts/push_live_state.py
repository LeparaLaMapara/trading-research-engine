"""Publish the LIVE state (balance, open positions, real trades) so the dashboard is current.

Read-only against the broker: balance, reconciliation and a spot quote move no money and need
no authority grant. Writes go to Supabase `making_money` with the service key, exactly as the
research sink does.

Why this exists: the dashboard could describe the research but not the trading. It read the
number of trades from an environment variable that a human had to remember to change, and it
had no idea a position was open. Numbers a person must maintain by hand are stale by design.

Run:  python -m scripts.push_live_state
      python -m scripts.push_live_state --dry-run     # print, write nothing
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

import requests
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOADealListReq,
    ProtoOAReconcileReq,
    ProtoOASubscribeSpotsReq,
    ProtoOATraderReq,
)
from twisted.internet import reactor

from config import settings
from connection.client import CTraderConnection

TRADE_LOG = "data/trade_log.db"
#: cTrader caps a deal-list request at one week. The job runs hourly, so a close is picked up
#: unless the job is down for seven days straight.
DEAL_WINDOW_MS = 7 * 24 * 3600 * 1000

#: Timestamps are written with a trailing Z, which means UTC. time.strftime() without an
#: argument uses LOCAL time, so the first version stamped SAST as UTC and the dashboard's
#: freshness check reported data "-0.6 hours old", i.e. from the future. Always pass gmtime().


def _lot_sizes() -> dict:
    """symbol -> lotSize, from the specs captured by scripts/fetch_swaps. Volume divided by
    lotSize is lots; guessing 100 turned 0.01 ETH into 1e-07."""
    try:
        import json
        with open("data/swaps.json", encoding="utf-8") as fh:
            return {k: int(v.get("lotSize", 0) or 0) for k, v in json.load(fh).items()}
    except (OSError, ValueError):
        return {}


def _headers() -> dict:
    return {"apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Content-Profile": settings.SUPABASE_SCHEMA,
            "Prefer": "resolution=merge-duplicates"}


def upsert(table: str, rows: list[dict], dry: bool) -> None:
    if not rows:
        print(f"  {table}: nothing to write")
        return
    if dry or not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
        print(f"  {table}: would write {len(rows)} row(s) {rows[:1]}")
        return
    r = requests.post(f"{settings.SUPABASE_URL}/rest/v1/{table}", headers=_headers(),
                      json=rows, timeout=30)
    print(f"  {table}: {r.status_code} {'ok' if r.status_code < 300 else r.text[:200]}")


def closed_trades() -> list[dict]:
    """Real orders from the SARS trade log. These are facts, not model output.

    The log lives on the machine that places orders. In CI it does not exist, which is
    expected, not an error: closes of tracked positions come from the broker instead
    (closing_deal_rows)."""
    import os
    if not os.path.exists(TRADE_LOG):
        print("  no local trade log here (normal in CI); closes come from the broker")
        return []
    try:
        c = sqlite3.connect(TRADE_LOG)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM trade_log WHERE purpose LIKE 'live%' OR purpose LIKE 'telemetry%' "
            "ORDER BY trade_id")]
        c.close()
    except sqlite3.Error as exc:
        print(f"  trade log unreadable: {exc}")
        return []
    out = []
    for r in rows:
        out.append({"trade_id": str(r["trade_id"]), "symbol": r["symbol"], "side": r["side"],
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["ts_utc"] or 0)),
                    "volume_lots": r["volume_lots"], "filled_price": r["filled_price"],
                    "stop_loss": r["stop_loss"], "take_profit": r["take_profit"],
                    "net_usd": r["net_pnl"], "status": r["status"], "purpose": r["purpose"],
                    "note": (r["note"] or "")[:400]})
    return out


def equity_of(balance: float, rows: list[dict]) -> float | None:
    """Balance plus each open position's unrealised P&L, swap and commission.

    None when any open position has no quote: an equity that silently leaves a position out
    is the same number as the balance, which is what this used to publish."""
    total = balance
    for r in rows:
        if r.get("unrealised_usd") is None:
            return None
        total += r["unrealised_usd"] + (r.get("swap_usd") or 0) + (r.get("commission_usd") or 0)
    return round(total, 2)


def closing_deal_rows(deals: list, tracked: dict[str, str], id_to_name: dict[int, str],
                      lots: dict[str, int]) -> list[dict]:
    """Trade rows for broker deals that CLOSED a position the dashboard tracks.

    `tracked` maps position_id -> purpose. Deals on other positions (telemetry probes, which
    round-trip inside one script) are left to the local trade log that already records them,
    so nothing is written twice."""
    out = []
    for d in deals:
        pid = str(d.positionId)
        if pid not in tracked or not d.HasField("closePositionDetail"):
            continue
        cp = d.closePositionDetail
        m = 10 ** (cp.moneyDigits or d.moneyDigits or 2)
        net = (cp.grossProfit + cp.swap + cp.commission - (cp.pnlConversionFee or 0)) / m
        sym = id_to_name.get(d.symbolId, str(d.symbolId))
        vol = d.filledVolume or d.volume
        out.append({
            "trade_id": f"deal-{d.dealId}", "symbol": sym,
            "side": "BUY" if d.tradeSide == 1 else "SELL",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(d.executionTimestamp / 1000)),
            "volume_lots": (vol / lots[sym]) if lots.get(sym) else None,
            "filled_price": d.executionPrice, "stop_loss": None, "take_profit": None,
            "net_usd": round(net, 2), "status": "CLOSED", "purpose": tracked[pid],
            "note": f"broker closing deal for position {pid}; net = gross + swap + commission"})
    return out


class Collector:
    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.conn = CTraderConnection(on_ready=self.on_ready, on_spot=self.on_spot)
        self.spots: dict[int, float] = {}
        self.positions: list = []
        self.balance = None
        self.id_to_name: dict[int, str] = {}
        self.deals: list = []

    def on_spot(self, ev) -> None:
        if getattr(ev, "bid", 0):
            self.spots[ev.symbolId] = ev.bid / 100000.0

    def on_ready(self, conn) -> None:
        self.id_to_name = {v: k for k, v in conn.name_to_id.items()}
        req = ProtoOATraderReq(); req.ctidTraderAccountId = conn.account_id
        conn.client.send(req).addCallbacks(self.on_trader, self.fail)

    def on_trader(self, msg) -> None:
        t = Protobuf.extract(msg).trader
        self.balance = t.balance / (10 ** t.moneyDigits)
        print(f"  balance ${self.balance:,.2f}")
        req = ProtoOAReconcileReq(); req.ctidTraderAccountId = self.conn.account_id
        self.conn.client.send(req).addCallbacks(self.on_reconcile, self.fail)

    def on_reconcile(self, msg) -> None:
        res = Protobuf.extract(msg)
        self.positions = list(res.position)
        print(f"  {len(self.positions)} open position(s)")
        now_ms = int(time.time() * 1000)
        dl = ProtoOADealListReq(); dl.ctidTraderAccountId = self.conn.account_id
        dl.fromTimestamp = now_ms - DEAL_WINDOW_MS; dl.toTimestamp = now_ms
        self.conn.client.send(dl).addCallbacks(self.on_deals, self.fail_soft)
        if not self.positions:
            reactor.callLater(5, self.finish)   # wait for the deal list only
            return
        sub = ProtoOASubscribeSpotsReq()
        sub.ctidTraderAccountId = self.conn.account_id
        for p in self.positions:
            sub.symbolId.append(p.tradeData.symbolId)
        self.conn.client.send(sub)
        reactor.callLater(8, self.finish)       # give the quotes a moment to arrive

    def on_deals(self, msg) -> None:
        self.deals = list(Protobuf.extract(msg).deal)
        print(f"  {len(self.deals)} deal(s) in the last 7 days")

    def fail_soft(self, f) -> None:
        print(f"  deal list failed (closes not published this hour): {str(f)[:120]}",
              file=sys.stderr)

    def fail(self, f) -> None:
        print(f"  broker request failed: {str(f)[:120]}", file=sys.stderr)
        self.finish()

    def finish(self) -> None:
        if getattr(self, "_finished", False):
            return
        self._finished = True
        rows = []
        lots = _lot_sizes()
        for p in self.positions:
            td = p.tradeData
            sym = self.id_to_name.get(td.symbolId, str(td.symbolId))
            units = td.volume / 100.0
            entry = p.price
            now = self.spots.get(td.symbolId)
            side = "BUY" if td.tradeSide == 1 else "SELL"
            unreal = None
            if now is not None:
                unreal = (now - entry) * units * (1 if side == "BUY" else -1)
            # What this position can still lose if the stop is hit. Computed here, where the
            # contract size is known, rather than guessed by the dashboard.
            risk = abs(entry - p.stopLoss) * units if p.stopLoss else None
            d = 10 ** getattr(p, "moneyDigits", 2)
            rows.append({
                "position_id": str(p.positionId), "symbol": sym, "side": side,
                "volume_lots": (td.volume / lots[sym]) if lots.get(sym) else None,
                "entry_price": entry, "current_price": now,
                "stop_loss": p.stopLoss or None, "take_profit": p.takeProfit or None,
                "unrealised_usd": unreal, "risk_usd": risk, "swap_usd": (p.swap or 0) / d,
                "commission_usd": (p.commission or 0) / d,
                "opened_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                           time.gmtime(td.openTimestamp / 1000)),
                "updated_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "OPEN",
                "purpose": "live_research_trade"})
            print(f"  {sym} {side} entry {entry} now {now} stop {p.stopLoss} "
                  f"target {p.takeProfit} unrealised "
                  f"{'n/a' if unreal is None else f'${unreal:+.2f}'}")
        self.rows = rows
        if reactor.running:
            reactor.stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    print("reading the live account (read-only)...")
    c = Collector(a.dry_run)
    c.rows = []
    c.run = c.conn.run
    c.run()

    print("publishing...")
    if c.balance is not None:
        equity = equity_of(c.balance, c.rows)
        print(f"  equity {'unknown (a position had no quote)' if equity is None else f'${equity:,.2f}'}")
        upsert("trading_account", [{"balance": c.balance, "equity": equity,
                                    "currency": "USD",
                                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}], a.dry_run)
    upsert("trading_positions", c.rows, a.dry_run)
    # Anything previously OPEN that the broker no longer reports has been closed.
    open_ids = {r["position_id"] for r in c.rows}
    tracked = {r["position_id"]: r["purpose"] for r in c.rows}
    if settings.SUPABASE_URL and settings.SUPABASE_KEY:
        try:
            got = requests.get(
                f"{settings.SUPABASE_URL}/rest/v1/trading_positions"
                f"?select=position_id,purpose,status",
                headers={"apikey": settings.SUPABASE_KEY,
                         "Authorization": f"Bearer {settings.SUPABASE_KEY}",
                         "Accept-Profile": settings.SUPABASE_SCHEMA}, timeout=20).json()
            tracked.update({r["position_id"]: r["purpose"] or "live_research_trade"
                            for r in got})
            stale = [r["position_id"] for r in got
                     if r["status"] == "OPEN" and r["position_id"] not in open_ids]
            if a.dry_run:
                stale = []
            for pid in stale:
                requests.patch(
                    f"{settings.SUPABASE_URL}/rest/v1/trading_positions?position_id=eq.{pid}",
                    headers=_headers(), json={"status": "CLOSED",
                                              "updated_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    timeout=20)
            if stale:
                print(f"  marked {len(stale)} position(s) closed")
        except Exception as exc:                # noqa: BLE001
            print(f"  could not reconcile closed positions: {exc}")
    upsert("trading_trades",
           closed_trades() + closing_deal_rows(c.deals, tracked, c.id_to_name, _lot_sizes()),
           a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
