"""Phase 1a passive telemetry logger.

Subscribes to the instrument basket, records every spot tick (spread in price and pips),
probes API latency on a timer, and on shutdown exports a hash-stamped Parquet snapshot.

PASSIVE ONLY: no orders, no strategy, no risk decisions, no AI. It never sends a
ProtoOANewOrderReq — verify with:  grep -R ProtoOANewOrder telemetry/  (no hits).

Run:  python -m telemetry.logger --duration 120      # log for 120s then snapshot
      python -m telemetry.logger                     # run until ctrl-c
"""
from __future__ import annotations

import argparse
import sys
import time

from ctrader_open_api.messages.OpenApiMessages_pb2 import (ProtoOADepthEvent,
                                                           ProtoOASubscribeDepthQuotesReq,
                                                           ProtoOAVersionReq)
from twisted.internet import reactor
from twisted.internet.task import LoopingCall

from config import instruments, settings
from connection.client import CTraderConnection
from telemetry import units
from telemetry.store import Store

SNAPSHOT_DIR = "data/snapshots"


class TelemetryLogger:
    def __init__(self, duration: int | None, symbols: list[str] | None = None,
                 with_depth: bool = False, snapshot: bool = True) -> None:
        self.with_depth = with_depth
        self.take_snapshot = snapshot
        # A focused basket matters for the sub-second band: recording 64 instruments to answer
        # a crypto question wastes disk and throughput on markets that are closed.
        self.symbols = [s.upper() for s in symbols] if symbols else None
        self.depth_count = 0
        self.duration = duration
        self.store = Store(settings.TELEMETRY_DB)
        self.id_to_name: dict[int, str] = {}
        self.spec: dict[int, dict] = {}          # symbol_id -> {digits, pip_position}
        self.last: dict[int, dict] = {}          # symbol_id -> {bid_raw, ask_raw}
        self.pending_specs: set[int] = set()
        self.subscribed = False
        self.tick_count = 0
        self._latency_loop: LoopingCall | None = None
        self.conn = CTraderConnection(
            on_ready=self.on_ready, on_spot=self.on_spot, on_symbol_spec=self.on_spec,
            on_depth=self.on_depth)

    def run(self) -> None:
        reactor.addSystemEventTrigger("before", "shutdown", self._on_reactor_shutdown)
        self.conn.run()

    # -- lifecycle ---------------------------------------------------------
    def on_ready(self, conn: CTraderConnection) -> None:
        ids, missing = [], []
        for name in (self.symbols or instruments.BASKET):
            sid = conn.name_to_id.get(name.upper())
            if sid is None:
                missing.append(name)
                continue
            ids.append(sid)
            self.id_to_name[sid] = name.upper()
        if missing:
            print(f"WARNING: not found on this account, skipping: {missing}", file=sys.stderr)
        if not ids:
            print("no basket symbols available; nothing to log.", file=sys.stderr)
            reactor.stop()
            return
        self.pending_specs = set(ids)
        print(f"fetching specs for {len(ids)} symbols…")
        conn.fetch_symbol_specs(ids)

    def on_spec(self, sym: object) -> None:
        self.spec[sym.symbolId] = {"digits": sym.digits, "pip_position": sym.pipPosition}
        self.store.upsert_symbol_spec({
            "symbol": self.id_to_name.get(sym.symbolId, str(sym.symbolId)),
            "symbol_id": sym.symbolId, "digits": sym.digits, "pip_position": sym.pipPosition,
            "lot_size": sym.lotSize, "min_volume": sym.minVolume, "step_volume": sym.stepVolume,
            "max_volume": sym.maxVolume, "swap_long": sym.swapLong, "swap_short": sym.swapShort,
            "captured_ts": time.time(),
        })
        self.pending_specs.discard(sym.symbolId)
        if not self.pending_specs and not self.subscribed:
            self._start_streaming(list(self.spec.keys()))

    def _subscribe_depth(self, ids: list[int]) -> None:
        """Level 2. The spot stream carries PRICES only, which is why 361k logged events
        contained no book. Sizes are what imbalance research needs."""
        # symbolId is a REPEATED field here (unlike ProtoOAExpectedMarginReq), so it is
        # appended, not assigned. One request covers the whole basket.
        req = ProtoOASubscribeDepthQuotesReq()
        req.ctidTraderAccountId = self.conn.account_id
        for sid in ids:
            req.symbolId.append(sid)
        self.conn.client.send(req)
        print(f"subscribed to depth for {len(ids)} symbols")

    def on_depth(self, event: object) -> None:
        sym = self.id_to_name.get(event.symbolId, str(event.symbolId))
        now = units.utc_now().timestamp()
        rows = []
        for q in event.newQuotes:
            side = "bid" if q.HasField("bid") else "ask"
            raw = q.bid if side == "bid" else q.ask
            rows.append({"ts_utc": now, "symbol": sym, "quote_id": q.id, "side": side,
                         "price": units.to_price(raw), "size": q.size, "event": "new"})
        for qid in event.deletedQuotes:
            rows.append({"ts_utc": now, "symbol": sym, "quote_id": qid, "side": "delete",
                         "price": None, "size": None, "event": "deleted"})
        self.store.insert_depth(rows)
        self.depth_count += len(rows)

    def _start_streaming(self, ids: list[int]) -> None:
        self.subscribed = True
        self.conn.subscribe_spots(ids)
        if self.with_depth:
            self._subscribe_depth(ids)
        print(f"subscribed to {len(ids)} symbols. Logging ticks…")
        self._latency_loop = LoopingCall(self._probe_latency)
        self._latency_loop.start(settings.LATENCY_INTERVAL_S, now=True)
        if self.duration:
            reactor.callLater(self.duration, self._shutdown)
            print(f"will snapshot and stop after {self.duration}s.")

    # -- data handlers -----------------------------------------------------
    def on_spot(self, event: object) -> None:
        sid = event.symbolId
        spec = self.spec.get(sid)
        if spec is None:
            return  # spec not yet known; skip (only possible in the first moments)
        st = self.last.setdefault(sid, {"bid_raw": None, "ask_raw": None})
        side_parts = []
        if event.HasField("bid"):
            st["bid_raw"] = event.bid
            side_parts.append("bid")
        if event.HasField("ask"):
            st["ask_raw"] = event.ask
            side_parts.append("ask")
        if st["bid_raw"] is None or st["ask_raw"] is None:
            return  # need both sides before a spread is meaningful
        digits, pip = spec["digits"], spec["pip_position"]
        now = units.utc_now()
        sast = units.to_sast(now)
        # The broker stamps the event in milliseconds. The gap to our receive time IS the
        # market-data latency, and it is the first of the brief's fifteen timestamps.
        server_ts = event.timestamp / 1000.0 if event.HasField("timestamp") else None
        recv_ms = (now.timestamp() - server_ts) * 1000.0 if server_ts else None
        self.store.insert_tick({
            "ts_utc": now.timestamp(),
            "ts_sast": sast.isoformat(),
            "dow_sast": sast.weekday(),
            "hour_sast": sast.hour,
            "hour_of_week": units.hour_of_week(sast),
            "symbol": self.id_to_name.get(sid, str(sid)),
            "bid_raw": st["bid_raw"], "ask_raw": st["ask_raw"],
            "digits": digits, "pip_position": pip,
            "bid": units.to_price(st["bid_raw"]),
            "ask": units.to_price(st["ask_raw"]),
            "spread_price": units.spread_price(st["bid_raw"], st["ask_raw"]),
            "spread_pips": units.spread_pips(st["bid_raw"], st["ask_raw"], pip),
            "side": "+".join(side_parts) or "both",
            "server_ts": server_ts, "recv_latency_ms": recv_ms,
        })
        self.tick_count += 1
        if self.tick_count % 200 == 0:
            print(f"  {self.tick_count} ticks logged…")

    def _probe_latency(self) -> None:
        t0 = time.time()
        d = self.conn.client.send(ProtoOAVersionReq())
        d.addCallback(lambda _r: self.store.insert_latency("version", (time.time() - t0) * 1000))
        d.addErrback(lambda f: print(f"latency probe failed: {f}", file=sys.stderr))

    # -- shutdown ----------------------------------------------------------
    def _shutdown(self) -> None:
        if reactor.running:
            reactor.stop()

    def _on_reactor_shutdown(self) -> None:
        if self._latency_loop and self._latency_loop.running:
            self._latency_loop.stop()
        print(f"\nstopping. total ticks: {self.tick_count}")
        if self.take_snapshot:
            self.store.snapshot(SNAPSHOT_DIR)
        self.store.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Passive cTrader execution telemetry logger.")
    p.add_argument("--symbols", nargs="*", default=None,
                   help="record only these symbols (default: the whole telemetry basket)")
    p.add_argument("--depth", action="store_true",
                   help="also subscribe to level-2 depth quotes (sizes per level)")
    p.add_argument("--duration", type=int, default=None,
                   help="seconds to log before snapshotting and stopping (default: until ctrl-c)")
    p.add_argument("--no-snapshot", action="store_true",
                   help="skip the Parquet export on stop. Each export copies EVERY tick in the "
                        "database, so a loop that restarts hourly would grow quadratically")
    args = p.parse_args()
    TelemetryLogger(args.duration, args.symbols, args.depth, not args.no_snapshot).run()


if __name__ == "__main__":
    main()
