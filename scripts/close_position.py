"""Close ONE live position by id, through the owner's authority, and log it.

scripts/reconcile.py can only close everything; this closes exactly the position named.

    python -m scripts.close_position --id 342510590 --reason "..."
"""
from __future__ import annotations

import argparse
import sys
import time

from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (ProtoOAClosePositionReq,
                                                       ProtoOAExecutionEvent,
                                                       ProtoOAReconcileReq)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAExecutionType
from twisted.internet import reactor

from connection.client import CTraderConnection
from ledger.trade_log import TradeLog
from ops.authority import live_trading_permitted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    out = {"closed": False, "error": None}

    def stop():
        if reactor.running:
            reactor.stop()

    def fail(f):
        out["error"] = str(f)[:200]
        stop()

    def on_ready(conn):
        auth = live_trading_permitted(conn.account_id)
        if not auth.permitted:
            out["error"] = f"no live authority: {auth.reason}"
            return stop()
        req = ProtoOAReconcileReq(); req.ctidTraderAccountId = conn.account_id

        def on_rec(msg):
            pos = [p for p in Protobuf.extract(msg).position if p.positionId == a.id]
            if not pos:
                out["error"] = f"position {a.id} is not open"
                return stop()
            p = pos[0]
            out["symbol"] = {v: k for k, v in conn.name_to_id.items()}.get(p.tradeData.symbolId)
            out["side"] = "SELL" if p.tradeData.tradeSide == 1 else "BUY"   # the closing side
            out["volume"] = p.tradeData.volume
            c = ProtoOAClosePositionReq()
            c.ctidTraderAccountId = conn.account_id
            c.positionId = a.id
            c.volume = p.tradeData.volume
            conn.client.send(c).addCallbacks(on_exec, fail)

        def on_exec(msg):
            # The reply to the request is usually ORDER_ACCEPTED, before any fill. The fill
            # arrives as a separate execution event, caught by `watch` below.
            ev = Protobuf.extract(msg)
            if getattr(ev, "executionType", None) in (ProtoOAExecutionType.ORDER_FILLED,
                                                      ProtoOAExecutionType.ORDER_ACCEPTED):
                out["closed"] = True
            reactor.callLater(5, stop)

        original = getattr(conn.client, "_messageReceivedCallback", None)

        def watch(client, message):
            if message.payloadType == ProtoOAExecutionEvent().payloadType:
                ev = Protobuf.extract(message)
                if ev.HasField("deal") and ev.deal.positionId == a.id:
                    out["price"] = ev.deal.executionPrice
                    if ev.deal.HasField("closePositionDetail"):
                        cp = ev.deal.closePositionDetail
                        m = 10 ** (cp.moneyDigits or 2)
                        out["net"] = round((cp.grossProfit + cp.swap + cp.commission) / m, 2)
            if original:
                original(client, message)

        conn.client.setMessageReceivedCallback(watch)
        conn.client.send(req).addCallbacks(on_rec, fail)

    reactor.callLater(60, stop)
    CTraderConnection(on_ready=on_ready).run()
    if out["closed"]:
        TradeLog("data/trade_log.db").record(
            ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"), symbol=out.get("symbol"),
            side=out.get("side"), order_type="MARKET", filled_price=out.get("price"),
            position_id=str(a.id), status="CLOSED", purpose="live_research_trade",
            net_pnl=out.get("net"),
            note=a.reason[:200] or "closed by scripts.close_position")
        print(f"closed position {a.id} at {out.get('price')}")
        return 0
    print(f"NOT closed: {out['error']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
