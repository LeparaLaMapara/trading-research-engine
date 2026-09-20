"""Reusable cTrader Open API connection bootstrap.

Runs the proven auth sequence (app auth -> account discovery -> account auth ->
symbols list), then hands control to the caller via `on_ready`. Spot events and full
symbol specs are forwarded to registered handlers. This is the shared connection layer
every phase builds on; it contains NO strategy, NO risk, NO order placement.

Mirrors the working sequence in ctrader-connect/connector/main.py.
"""
from __future__ import annotations

import sys
from typing import Callable

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAErrorRes,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOASpotEvent,
    ProtoOASubscribeSpotsReq,
    ProtoOASymbolByIdReq,
    ProtoOADepthEvent,
    ProtoOASymbolByIdRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
)
from twisted.internet import reactor

from config import settings
from connection import tokens

HOST = EndPoints.PROTOBUF_LIVE_HOST if settings.ENV == "live" else EndPoints.PROTOBUF_DEMO_HOST

# Handler type aliases (for readability)
OnReady = Callable[["CTraderConnection"], None]
OnSpot = Callable[[object], None]          # receives a ProtoOASpotEvent
OnSymbolSpec = Callable[[object], None]     # receives a ProtoOASymbol


class CTraderConnection:
    """Owns the client and the auth state machine. Register handlers, then run()."""

    def __init__(self, on_ready: OnReady, on_spot: OnSpot | None = None,
                 on_symbol_spec: OnSymbolSpec | None = None,
                 on_depth=None) -> None:
        self.on_depth = on_depth
        self.on_ready = on_ready
        self.on_spot = on_spot
        self.on_symbol_spec = on_symbol_spec
        self.account_id: int | None = int(settings.ACCOUNT_ID) if settings.ACCOUNT_ID else None
        self.name_to_id: dict[str, int] = {}
        self.accounts: list = []      # every account the token reaches, filled during setup
        self._access_token: str | None = None
        self._refresh_attempted = False
        self.client = Client(HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> None:
        if not settings.CLIENT_ID or not settings.CLIENT_SECRET:
            print("set CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET first.", file=sys.stderr)
            sys.exit(1)
        self.client.startService()
        reactor.run()

    def _on_connected(self, client: Client) -> None:
        print(f"connected to {HOST}:{EndPoints.PROTOBUF_PORT} ({settings.ENV})")
        req = ProtoOAApplicationAuthReq()
        req.clientId = settings.CLIENT_ID
        req.clientSecret = settings.CLIENT_SECRET
        client.send(req)

    def _on_disconnected(self, client: Client, reason: object) -> None:
        print(f"disconnected: {reason}", file=sys.stderr)

    def _err(self, failure: object) -> None:
        print(f"request failed: {failure}", file=sys.stderr)

    # -- convenience for callers ------------------------------------------
    def fetch_symbol_specs(self, symbol_ids: list[int]) -> None:
        req = ProtoOASymbolByIdReq()
        req.ctidTraderAccountId = self.account_id
        for sid in symbol_ids:
            req.symbolId.append(sid)
        self.client.send(req).addErrback(self._err)

    def subscribe_spots(self, symbol_ids: list[int]) -> None:
        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = self.account_id
        for sid in symbol_ids:
            req.symbolId.append(sid)
        self.client.send(req).addErrback(self._err)

    # -- auth state machine -----------------------------------------------
    def _on_message(self, client: Client, message: object) -> None:
        if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
            print("application authenticated")
            self._access_token = tokens.access_token()
            if not self._access_token:
                print("no access token; run the ctrader-connect OAuth flow first.", file=sys.stderr)
                reactor.stop()
                return
            req = ProtoOAGetAccountListByAccessTokenReq()
            req.accessToken = self._access_token
            client.send(req).addErrback(self._err)

        elif message.payloadType == ProtoOAGetAccountListByAccessTokenRes().payloadType:
            res = Protobuf.extract(message)
            accounts = list(res.ctidTraderAccount)
            # Keep it. The connection already asks for this during setup, and anything that
            # re-requests it triggers the account-auth branch again and gets ALREADY_LOGGED_IN.
            self.accounts = accounts
            if not accounts:
                print("token grants no trading accounts.", file=sys.stderr)
                reactor.stop()
                return
            if self.account_id is None:
                self.account_id = accounts[0].ctidTraderAccountId
                print(f"CTRADER_ACCOUNT_ID not set; using first: {self.account_id}")
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = self.account_id
            req.accessToken = self._access_token
            client.send(req).addErrback(self._err)

        elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
            print(f"account {self.account_id} authenticated")
            self._refresh_attempted = False   # fresh retry budget per auth cycle
            req = ProtoOASymbolsListReq()
            req.ctidTraderAccountId = self.account_id
            client.send(req).addErrback(self._err)

        elif message.payloadType == ProtoOASymbolsListRes().payloadType:
            res = Protobuf.extract(message)
            self.name_to_id = {s.symbolName.upper(): s.symbolId for s in res.symbol}
            print(f"symbols available: {len(self.name_to_id)}")
            self.on_ready(self)

        elif message.payloadType == ProtoOASymbolByIdRes().payloadType:
            res = Protobuf.extract(message)
            if self.on_symbol_spec:
                for sym in res.symbol:
                    self.on_symbol_spec(sym)

        elif message.payloadType == ProtoOASpotEvent().payloadType:
            if self.on_spot:
                self.on_spot(Protobuf.extract(message))

        elif message.payloadType == ProtoOADepthEvent().payloadType:
            if self.on_depth:
                self.on_depth(Protobuf.extract(message))

        elif message.payloadType == ProtoOAErrorRes().payloadType:
            res = Protobuf.extract(message)
            print(f"API error {res.errorCode}: {res.description}", file=sys.stderr)
            if "ACCESS_TOKEN" in res.errorCode and not self._refresh_attempted:
                self._refresh_attempted = True
                print("access token rejected; attempting refresh...", file=sys.stderr)
                try:
                    self._access_token = tokens.refresh()["access_token"]
                    req = ProtoOAGetAccountListByAccessTokenReq()
                    req.accessToken = self._access_token
                    client.send(req).addErrback(self._err)
                except Exception as exc:  # noqa: BLE001
                    print(f"refresh failed: {exc}. Re-run the OAuth flow.", file=sys.stderr)
                    reactor.stop()
