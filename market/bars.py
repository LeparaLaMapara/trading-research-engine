"""Fetch historical trendbars (OHLC) from cTrader and store them for backtesting.

cTrader encodes each trendbar as an absolute `low` plus deltas, all at the fixed 1e5 price
scale (same scale the telemetry work verified). Reconstruct:
    low = tb.low / 1e5
    open  = (tb.low + tb.deltaOpen)  / 1e5
    high  = (tb.low + tb.deltaHigh)  / 1e5
    close = (tb.low + tb.deltaClose) / 1e5

One-shot: connect -> auth -> request bars -> store -> stop. No strategy, no orders.

Run:  python -m market.bars --symbol EURUSD --period H1 --days 180
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time

import pandas as pd
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import reactor

from config import settings
from connection.client import CTraderConnection

MARKET_DB = "data/market.db"
SNAPSHOT_DIR = "data/snapshots"
PRICE_SCALE = 1e5

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    PRIMARY KEY (symbol, period, ts_utc)
);
"""


# The broker truncates a single trendbar response at roughly 14,000 bars. Measured, not
# assumed: 730 days of H1 returned 12,429 and 1,825 days returned exactly 13,999. So deep
# history has to be walked backwards in chunks rather than asked for in one request.
MAX_BARS_PER_REQUEST = 13_000
BARS_PER_DAY = {"M1": 1440, "M5": 288, "M15": 96, "M30": 48,
                "H1": 24, "H4": 6, "D1": 1, "W1": 0.2}


class BarsFetcher:
    def __init__(self, symbol: str, period: str, days: int) -> None:
        self.symbol = symbol.upper()
        self.period = period.upper()
        self.days = days
        self.rows: list[dict] = []
        # Walk backwards in chunks sized so each request stays under the truncation limit.
        per_day = BARS_PER_DAY.get(self.period, 24)
        self.chunk_days = max(1, int(MAX_BARS_PER_REQUEST / max(per_day, 0.2)))
        self.cursor_ms = int(time.time() * 1000)
        self.floor_ms = self.cursor_ms - days * 86400 * 1000
        self.empty_chunks = 0
        self.conn = CTraderConnection(on_ready=self.on_ready)

    def run(self) -> None:
        self.conn.run()

    def on_ready(self, conn: CTraderConnection) -> None:
        sid = conn.name_to_id.get(self.symbol)
        if sid is None:
            print(f"symbol {self.symbol} not found on this account.", file=sys.stderr)
            reactor.stop()
            return
        self.sid = sid
        print(f"fetching {self.days} days of {self.period} for {self.symbol} "
              f"in {self.chunk_days}-day chunks…")
        self._request_chunk()

    def _request_chunk(self) -> None:
        if self.cursor_ms <= self.floor_ms or self.empty_chunks >= 2:
            # Two empty chunks in a row means the broker has no more history for this
            # symbol. Stop rather than grinding backwards through nothing.
            print(f"received {len(self.rows)} bars total.")
            self._store()
            if reactor.running:
                reactor.stop()
            return
        start = max(self.cursor_ms - self.chunk_days * 86400 * 1000, self.floor_ms)
        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId = self.sid
        req.period = ProtoOATrendbarPeriod.Value(self.period)
        req.fromTimestamp = start
        req.toTimestamp = self.cursor_ms
        self.cursor_ms = start
        self.conn.client.send(req).addCallbacks(self.on_bars, self._err)

    def _err(self, failure: object) -> None:
        print(f"trendbars request failed: {failure}", file=sys.stderr)
        reactor.stop()

    def on_bars(self, message: object) -> None:
        res = Protobuf.extract(message)
        for tb in res.trendbar:
            low = tb.low
            self.rows.append({
                "symbol": self.symbol, "period": self.period,
                "ts_utc": tb.utcTimestampInMinutes * 60,
                "open": (low + tb.deltaOpen) / PRICE_SCALE,
                "high": (low + tb.deltaHigh) / PRICE_SCALE,
                "low": low / PRICE_SCALE,
                "close": (low + tb.deltaClose) / PRICE_SCALE,
                "volume": tb.volume,
            })
        got = len(res.trendbar)
        self.empty_chunks = self.empty_chunks + 1 if got == 0 else 0
        print(f"  chunk: {got:>6} bars  (running total {len(self.rows)})")
        # Chain the next chunk rather than looping, because the client is asynchronous.
        reactor.callLater(0.4, self._request_chunk)

    def _store(self) -> None:
        if not self.rows:
            print("no bars returned.", file=sys.stderr)
            return
        os.makedirs(os.path.dirname(MARKET_DB) or ".", exist_ok=True)
        db = sqlite3.connect(MARKET_DB)
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT OR REPLACE INTO bars (symbol,period,ts_utc,open,high,low,close,volume) "
            "VALUES (:symbol,:period,:ts_utc,:open,:high,:low,:close,:volume)", self.rows)
        db.commit()
        df = pd.DataFrame(self.rows).sort_values("ts_utc").reset_index(drop=True)
        canonical = df.to_csv(index=False, lineterminator="\n").encode()
        digest = hashlib.sha256(canonical).hexdigest()
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        path = os.path.join(SNAPSHOT_DIR, f"bars_{self.symbol}_{self.period}_{digest[:12]}.parquet")
        df.to_parquet(path, index=False)
        db.close()
        print(f"stored {len(df)} bars -> {MARKET_DB} and {path}  sha256={digest[:12]}…")


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch historical trendbars from cTrader.")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--period", default="H1")
    p.add_argument("--days", type=int, default=180,
                   help="how far back to walk; chunked automatically past the broker limit")
    p.add_argument("--years", type=float, default=None,
                   help="convenience: --years 5 is --days 1825")
    args = p.parse_args()
    if not settings.CLIENT_ID:
        print("set credentials in .env first.", file=sys.stderr)
        sys.exit(1)
    days = int(args.years * 365) if args.years else args.days
    BarsFetcher(args.symbol, args.period, days).run()


if __name__ == "__main__":
    main()
