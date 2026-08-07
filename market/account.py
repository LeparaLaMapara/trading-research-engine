"""Fetch the live cTrader account balance and record it (Supabase + stdout). Read-only."""
from __future__ import annotations

import sys

from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOATraderReq
from twisted.internet import reactor

from config import settings
from connection.client import CTraderConnection
from research import supabase_sink


class AccountFetcher:
    def __init__(self) -> None:
        self.conn = CTraderConnection(on_ready=self.on_ready)

    def run(self) -> None:
        self.conn.run()

    def on_ready(self, conn: CTraderConnection) -> None:
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = conn.account_id
        conn.client.send(req).addCallbacks(self.on_trader, self._err)

    def _err(self, failure: object) -> None:
        print(f"trader request failed: {failure}", file=sys.stderr)
        if reactor.running:
            reactor.stop()

    def on_trader(self, message: object) -> None:
        t = Protobuf.extract(message).trader
        balance = t.balance / (10 ** t.moneyDigits)     # cents -> real, per moneyDigits
        print(f"account {t.ctidTraderAccountId}  balance={balance}")
        supabase_sink.push_account(balance, balance, "USD", str(t.ctidTraderAccountId))
        if reactor.running:
            reactor.stop()


def main() -> None:
    if not settings.CLIENT_ID:
        print("set CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET first.", file=sys.stderr)
        sys.exit(1)
    AccountFetcher().run()


if __name__ == "__main__":
    main()
