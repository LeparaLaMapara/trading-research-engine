"""Safety tool: list open positions/orders on the live account, and optionally close them.

Read-only by default. With --close-all it closes every open position by positionId
(works on netting or hedging accounts). Use this after any probe that did not confirm a
clean close.

  python -m scripts.reconcile                # just list what's open
  python -m scripts.reconcile --close-all    # close every open position
"""
from __future__ import annotations

import argparse
import sys

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAClosePositionReq,
    ProtoOAErrorRes,
    ProtoOAExecutionEvent,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOAReconcileReq,
    ProtoOAReconcileRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAExecutionType
from twisted.internet import reactor

from config import settings
from connection import tokens

HOST = EndPoints.PROTOBUF_LIVE_HOST if settings.ENV == "live" else EndPoints.PROTOBUF_DEMO_HOST


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="List and optionally close open positions.")
    p.add_argument("--close-all", action="store_true", help="close every open position")
    return p.parse_args()


ARGS = parse_args()


class Reconcile:
    def __init__(self) -> None:
        self.client = Client(HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setMessageReceivedCallback(self._on_message)
        self.account_id = int(settings.ACCOUNT_ID) if settings.ACCOUNT_ID else None
        self.access_token = None
        self.pending_closes: set[int] = set()
        self.exit_code = 0

    def run(self) -> None:
        self.client.startService()
        reactor.callLater(30, self._timeout)
        reactor.run()
        sys.exit(self.exit_code)

    def _timeout(self) -> None:
        if self.pending_closes:
            print(f"still waiting on closes: {self.pending_closes}", file=sys.stderr)
            self.exit_code = 2
        self._stop()

    def _stop(self) -> None:
        if reactor.running:
            reactor.stop()

    def _on_connected(self, client: Client) -> None:
        print(f"connected to {HOST} ({settings.ENV})")
        req = ProtoOAApplicationAuthReq()
        req.clientId = settings.CLIENT_ID
        req.clientSecret = settings.CLIENT_SECRET
        client.send(req)

    def _err(self, failure: object) -> None:
        print(f"request failed: {failure}", file=sys.stderr)

    def _on_message(self, client: Client, message: object) -> None:
        pt = message.payloadType
        if pt == ProtoOAApplicationAuthRes().payloadType:
            self.access_token = tokens.access_token()
            req = ProtoOAGetAccountListByAccessTokenReq()
            req.accessToken = self.access_token
            client.send(req).addErrback(self._err)
        elif pt == ProtoOAGetAccountListByAccessTokenRes().payloadType:
            res = Protobuf.extract(message)
            if self.account_id is None and res.ctidTraderAccount:
                self.account_id = res.ctidTraderAccount[0].ctidTraderAccountId
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = self.account_id
            req.accessToken = self.access_token
            client.send(req).addErrback(self._err)
        elif pt == ProtoOAAccountAuthRes().payloadType:
            print(f"account {self.account_id} authenticated; reconciling...")
            req = ProtoOAReconcileReq()
            req.ctidTraderAccountId = self.account_id
            client.send(req).addErrback(self._err)
        elif pt == ProtoOAReconcileRes().payloadType:
            res = Protobuf.extract(message)
            positions = list(res.position)
            orders = list(res.order)
            print(f"\nOPEN POSITIONS: {len(positions)}")
            for p in positions:
                td = p.tradeData
                side = "BUY" if td.tradeSide == 1 else "SELL"
                print(f"  positionId={p.positionId}  symbolId={td.symbolId}  "
                      f"{side}  volume={td.volume}  status={p.positionStatus}")
            print(f"PENDING ORDERS: {len(orders)}")
            for o in orders:
                print(f"  orderId={o.orderId}  status={o.orderStatus}")
            if ARGS.close_all and positions:
                for p in positions:
                    self.pending_closes.add(p.positionId)
                    req = ProtoOAClosePositionReq()
                    req.ctidTraderAccountId = self.account_id
                    req.positionId = p.positionId
                    req.volume = p.tradeData.volume
                    print(f"closing position {p.positionId}...")
                    client.send(req).addErrback(self._err)
            else:
                self._stop()
        elif pt == ProtoOAExecutionEvent().payloadType:
            res = Protobuf.extract(message)
            if res.executionType == ProtoOAExecutionType.ORDER_FILLED and res.HasField("position"):
                pid = res.position.positionId
                if res.position.positionStatus == 2:   # POSITION_STATUS_CLOSED
                    print(f"position {pid} CLOSED")
                    self.pending_closes.discard(pid)
                    if not self.pending_closes:
                        self._stop()
        elif pt == ProtoOAErrorRes().payloadType:
            res = Protobuf.extract(message)
            print(f"API error {res.errorCode}: {res.description}", file=sys.stderr)


def main() -> None:
    Reconcile().run()


if __name__ == "__main__":
    main()
