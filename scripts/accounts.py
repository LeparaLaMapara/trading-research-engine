"""List every cTrader account the access token grants, with live/demo flag. Read-only.

The account list is the same on either host; you can only *authenticate* an account on
its matching host (demo accounts on demo, live on live).

  python -m scripts.accounts
"""
from __future__ import annotations

import sys

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAErrorRes,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
)
from twisted.internet import reactor

from config import settings
from connection import tokens

HOST = EndPoints.PROTOBUF_LIVE_HOST if settings.ENV == "live" else EndPoints.PROTOBUF_DEMO_HOST


def _on_message(client, message):
    pt = message.payloadType
    if pt == ProtoOAApplicationAuthRes().payloadType:
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = tokens.access_token()
        client.send(req)
    elif pt == ProtoOAGetAccountListByAccessTokenRes().payloadType:
        res = Protobuf.extract(message)
        print(f"accounts granted by this token: {len(res.ctidTraderAccount)}")
        for a in res.ctidTraderAccount:
            kind = "LIVE" if a.isLive else "DEMO"
            print(f"  ctidTraderAccountId={a.ctidTraderAccountId}  {kind}")
        if reactor.running:
            reactor.stop()
    elif pt == ProtoOAErrorRes().payloadType:
        res = Protobuf.extract(message)
        print(f"API error {res.errorCode}: {res.description}", file=sys.stderr)
        if reactor.running:
            reactor.stop()


def _on_connected(client):
    print(f"connected to {HOST} ({settings.ENV})")
    req = ProtoOAApplicationAuthReq()
    req.clientId = settings.CLIENT_ID
    req.clientSecret = settings.CLIENT_SECRET
    client.send(req)


def main():
    client = Client(HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
    client.setConnectedCallback(_on_connected)
    client.setMessageReceivedCallback(_on_message)
    client.startService()
    reactor.callLater(25, lambda: reactor.running and reactor.stop())
    reactor.run()


if __name__ == "__main__":
    main()
