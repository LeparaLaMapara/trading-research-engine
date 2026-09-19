"""Read the broker's CURRENT swap (overnight financing) terms for every research instrument.

Read-only: symbol specs move no money. Output: data/swaps.json, one record per symbol with
the raw broker fields, so the conversion to an annual rate is done (and can be re-done) in
plain code rather than trusted from here.

Run:  python -m scripts.fetch_swaps
"""
from __future__ import annotations

import json
import time

from twisted.internet import reactor

from config.instruments import extended_universe
from connection.client import CTraderConnection

OUT = "data/swaps.json"
FIELDS = ("symbolId", "digits", "pipPosition", "lotSize", "minVolume", "swapLong", "swapShort",
          "swapCalculationType", "swapRollover3Days", "swapPeriod", "swapTime", "leverageId",
          "measurementUnits", "commission", "commissionType", "preciseMinCommission")


def main() -> None:
    want = extended_universe()
    got: dict[str, dict] = {}

    def on_spec(sym) -> None:
        name = id_to_name.get(sym.symbolId)
        rec = {}
        for f in FIELDS:
            try:
                if sym.HasField(f):
                    rec[f] = getattr(sym, f)
            except ValueError:
                v = getattr(sym, f, None)
                if v not in (None, ""):
                    rec[f] = v
        rec["captured_ts"] = time.time()
        got[name] = rec
        if len(got) >= len(ids):
            json.dump(got, open(OUT, "w"), indent=1, default=str)
            print(f"wrote {len(got)} symbols to {OUT}")
            reactor.stop()

    def on_ready(conn: CTraderConnection) -> None:
        global id_to_name, ids
        ids = [conn.name_to_id[s] for s in want if s in conn.name_to_id]
        id_to_name = {conn.name_to_id[s]: s for s in want if s in conn.name_to_id}
        conn.fetch_symbol_specs(ids)
        reactor.callLater(60, lambda: (json.dump(got, open(OUT, "w"), indent=1, default=str),
                                       print(f"timeout: wrote {len(got)}"), reactor.stop())
                          if reactor.running else None)

    CTraderConnection(on_ready=on_ready, on_symbol_spec=on_spec).run()


id_to_name: dict[int, str] = {}
ids: list[int] = []

if __name__ == "__main__":
    main()
