"""Find the way this broker actually accepts a stop loss. DEMO ONLY.

The rehearsal proved positions were opening UNPROTECTED: both `stopLoss`/`takeProfit` as
absolute prices and `relativeStopLoss`/`relativeTakeProfit` as points came back 0.0 on the
filled position. A system that cannot attach a stop has no business near real money, so this
exists to settle the question empirically rather than by reading documentation.

It opens ONE minimum-size position, tries each approach in turn, asks the broker what the
position actually carries after each, and closes everything before exiting.

Run:  python -m scripts.stop_probe          # demo only, enforced
"""
from __future__ import annotations

import sys
import time

from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAmendPositionSLTPReq,
    ProtoOAClosePositionReq,
    ProtoOANewOrderReq,
    ProtoOAOrderErrorEvent,
    ProtoOAReconcileReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
)
from twisted.internet import reactor

from connection.client import CTraderConnection

SYMBOL = "EURUSD"
VOLUME = 100000          # minimum size; this is a diagnostic, not a trade
RESULTS: list[tuple[str, bool, str]] = []


def note(approach: str, protected: bool, detail: str) -> None:
    RESULTS.append((approach, protected, detail))
    print(f"  [{'PROTECTED  ' if protected else 'unprotected'}] {approach}: {detail}",
          flush=True)


class StopProbe:
    def __init__(self) -> None:
        self.conn = CTraderConnection(on_ready=self.ready)
        self.pid = None
        self.entry = None

    def ready(self, conn) -> None:
        # Same gate as everywhere else: ask the broker, never the configuration.
        demo = None
        for a in getattr(conn, "accounts", []) or []:
            if a.ctidTraderAccountId == conn.account_id:
                demo = not a.isLive
        if demo is not True:
            print("REFUSING: this is not a broker-confirmed demo account.", file=sys.stderr)
            return self.stop()
        self.sid = conn.name_to_id[SYMBOL]
        print(f"\nstop probe on {SYMBOL}, demo account {conn.account_id}\n", flush=True)
        print("attempt 1: relative stop/target on the market order itself", flush=True)
        r = ProtoOANewOrderReq()
        r.ctidTraderAccountId = conn.account_id
        r.symbolId = self.sid
        r.orderType = ProtoOAOrderType.Value("MARKET")
        r.tradeSide = ProtoOATradeSide.Value("BUY")
        r.volume = VOLUME
        r.relativeStopLoss = 200      # 20 pips in points on a 5-digit symbol
        r.relativeTakeProfit = 300
        r.label = "stop_probe"
        conn.client.send(r)
        reactor.callLater(10, self.after_order)

    def _reconcile(self, then) -> None:
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.conn.account_id

        def ok(msg):
            res = Protobuf.extract(msg)
            if not res.position:
                print("   no position open", flush=True)
                return self.stop()
            p = res.position[0]
            self.pid = p.positionId
            self.entry = p.price
            then(p)

        def err(f):
            print(f"   reconcile failed: {str(f)[:90]}", flush=True)
            self.close_and_stop()
        self.conn.client.send(req).addCallbacks(ok, err)

    def after_order(self) -> None:
        def check(p):
            note("relative points on the order", bool(p.stopLoss),
                 f"entry {p.price}, stopLoss {p.stopLoss}, takeProfit {p.takeProfit}")
            self.try_amend()
        self._reconcile(check)

    def try_amend(self) -> None:
        print("\nattempt 2: amend the OPEN position with absolute prices", flush=True)
        a = ProtoOAAmendPositionSLTPReq()
        a.ctidTraderAccountId = self.conn.account_id
        a.positionId = self.pid
        a.stopLoss = round(self.entry - 0.0020, 5)
        a.takeProfit = round(self.entry + 0.0030, 5)
        print(f"   amending {self.pid}: stop {a.stopLoss}, target {a.takeProfit}", flush=True)
        self.conn.client.send(a)
        reactor.callLater(10, self.after_amend)

    def after_amend(self) -> None:
        def check(p):
            note("amend position with absolute prices", bool(p.stopLoss),
                 f"stopLoss {p.stopLoss}, takeProfit {p.takeProfit}")
            self.close_and_stop()
        self._reconcile(check)

    def close_and_stop(self) -> None:
        if self.pid:
            print("\n   closing the probe position", flush=True)
            c = ProtoOAClosePositionReq()
            c.ctidTraderAccountId = self.conn.account_id
            c.positionId = self.pid
            c.volume = VOLUME
            self.conn.client.send(c)
        reactor.callLater(12, self.stop)

    def stop(self) -> None:
        if reactor.running:
            reactor.stop()

    def run(self) -> None:
        self.conn.run()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    probe = StopProbe()
    original = probe.conn._on_message

    def dispatch(client, message):
        if message.payloadType == ProtoOAOrderErrorEvent().payloadType:
            r = Protobuf.extract(message)
            print(f"   ORDER ERROR {r.errorCode}: {getattr(r, 'description', '')}", flush=True)
        original(client, message)

    probe.conn.client.setMessageReceivedCallback(dispatch)
    probe.run()

    print()
    working = [r for r in RESULTS if r[1]]
    if working:
        print(f"WORKS: {working[0][0]}")
    else:
        print("NOTHING attached a stop. Live trading stays blocked.")
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
