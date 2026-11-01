"""One cTrader session per hour: read the live bid and ask of every universe instrument and
refresh its last few days of hourly bars. Reads only; never sends an order.
"""
from __future__ import annotations

import sqlite3
import sys
import time

from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import reactor

from connection.client import CTraderConnection
from market.bars import MARKET_DB, PRICE_SCALE, SCHEMA

QUOTE_WAIT_S = 20
BAR_DAYS = 6


class Snapshot:
    def __init__(self, symbols: list[str]) -> None:
        self.want = [s.upper() for s in symbols]
        self.quotes: dict[str, dict] = {}
        self.bars: list[dict] = []
        self.missing: list[str] = []
        self.conn = CTraderConnection(on_ready=self.on_ready, on_spot=self.on_spot)

    def run(self) -> "Snapshot":
        reactor.callLater(240, self._timeout)
        self.conn.run()
        return self

    def _timeout(self) -> None:
        print("snapshot timed out", file=sys.stderr)
        if reactor.running:
            reactor.stop()

    def on_ready(self, conn: CTraderConnection) -> None:
        self.ids = {s: conn.name_to_id[s] for s in self.want if s in conn.name_to_id}
        self.missing = [s for s in self.want if s not in self.ids]
        self.by_id = {v: k for k, v in self.ids.items()}
        self._raw: dict[int, dict] = {}
        conn.subscribe_spots(list(self.ids.values()))
        self.queue = list(self.ids)
        reactor.callLater(1.0, self._next_bars)

    def on_spot(self, ev) -> None:
        st = self._raw.setdefault(ev.symbolId, {})
        if ev.HasField("bid"):
            st["bid"] = ev.bid
        if ev.HasField("ask"):
            st["ask"] = ev.ask
        sym = self.by_id.get(ev.symbolId)
        if sym and "bid" in st and "ask" in st and sym not in self.quotes:
            self.quotes[sym] = {"bid": st["bid"] / PRICE_SCALE, "ask": st["ask"] / PRICE_SCALE,
                                "recv_ts": time.time()}

    def _next_bars(self) -> None:
        if not self.queue:
            reactor.callLater(max(0.0, QUOTE_WAIT_S - (time.time() - self._t0())), self._finish)
            return
        sym = self.queue.pop(0)
        now = int(time.time() * 1000)
        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId = self.ids[sym]
        req.period = ProtoOATrendbarPeriod.Value("H1")
        req.fromTimestamp = now - BAR_DAYS * 86400 * 1000
        req.toTimestamp = now
        d = self.conn.client.send(req)
        d.addCallbacks(lambda m, s=sym: self._on_bars(s, m), lambda f, s=sym: self._bars_err(s, f))

    def _t0(self) -> float:
        if not hasattr(self, "_start"):
            self._start = time.time()
        return self._start

    def _on_bars(self, sym: str, message) -> None:
        self._t0()
        res = Protobuf.extract(message)
        for tb in res.trendbar:
            low = tb.low
            self.bars.append({"symbol": sym, "period": "H1", "ts_utc": tb.utcTimestampInMinutes * 60,
                              "open": (low + tb.deltaOpen) / PRICE_SCALE,
                              "high": (low + tb.deltaHigh) / PRICE_SCALE, "low": low / PRICE_SCALE,
                              "close": (low + tb.deltaClose) / PRICE_SCALE, "volume": tb.volume})
        reactor.callLater(0.25, self._next_bars)

    def _bars_err(self, sym: str, failure) -> None:
        print(f"bars failed for {sym}: {failure}", file=sys.stderr)
        reactor.callLater(0.25, self._next_bars)

    def _finish(self) -> None:
        now = time.time()
        # Keep only bars that have CLOSED: a bar opening at t closes at t + 3600.
        done = [b for b in self.bars if b["ts_utc"] + 3600 <= now]
        with sqlite3.connect(MARKET_DB) as db:
            db.executescript(SCHEMA)
            db.executemany("INSERT OR REPLACE INTO bars (symbol,period,ts_utc,open,high,low,close,volume) "
                           "VALUES (:symbol,:period,:ts_utc,:open,:high,:low,:close,:volume)", done)
        self.bars = done
        if reactor.running:
            reactor.stop()
