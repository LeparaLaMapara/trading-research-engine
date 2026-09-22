"""One decision of the autonomous live trader (E05: Ethereum 20-day trend).

Run once an hour by scripts/engine_loop.py. It decides at most once per UTC day, as the rule
was tested (docs/programme/E05-eth-trend-live-prereg.md):

  1. keep the owner's standing grant alive (ops.authority.ensure_standing);
  2. refresh ETHUSD daily bars and compute the signal from COMPLETED days only;
  3. read the account and the positions the engine itself opened (label engine-E05);
  4. close the engine's position if the signal no longer agrees with it;
  5. if the engine holds nothing, open in the signal's direction through scripts.live_trade,
     which sizes from the signed limits and attaches a broker-side stop and target.

Hard stop: the first time equity is seen below the signed floor ($20), the engine latches
`halted` in its state file and never opens again until the owner deletes that flag.

    python -m scripts.trader_step            # live (standing authority)
    python -m scripts.trader_step --dry-run  # decide and print, send nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time

import pandas as pd
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (ProtoOAClosePositionReq,
                                                       ProtoOAReconcileReq, ProtoOATraderReq)
from twisted.internet import reactor

from config import settings
from connection.client import CTraderConnection
from lab import eth_trend as E
from ops import authority
from risk.limits import LIVE_LIMITS

SYMBOL, LABEL = "ETHUSD", "engine-E05"
STATE = "data/engine_state.json"
DECISIONS = "data/engine_decisions.jsonl"
PY = sys.executable


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1)


def log_decision(d: dict) -> None:
    d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **d}
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(d) + "\n")
    print(json.dumps(d))


def completed_closes(today_utc: pd.Timestamp) -> pd.Series:
    """Daily closes of days that have ENDED. Today's bar is still forming and is excluded."""
    with sqlite3.connect("data/market.db") as c:
        df = pd.read_sql_query("SELECT ts_utc, close FROM bars WHERE symbol=? AND period='D1' "
                               "ORDER BY ts_utc", c, params=(SYMBOL,))
    df = df[df["ts_utc"] < today_utc.timestamp()]
    return df["close"].reset_index(drop=True)


class Broker:
    """One connection: read balance and positions, close the engine's position if it
    disagrees with `want` (and closing is allowed), then stop. Twisted's reactor cannot be
    restarted in one process, so reading and closing must share this single run."""

    def __init__(self, want: int, may_close: bool):
        self.want, self.may_close = want, may_close
        self.balance, self.positions, self.error = None, [], None
        self.closed_id = None
        self.conn = CTraderConnection(on_ready=self.on_ready)

    def run(self) -> "Broker":
        reactor.callLater(60, self._stop)
        self.conn.run()
        return self

    def _stop(self) -> None:
        if reactor.running:
            reactor.stop()

    def _fail(self, f) -> None:
        self.error = str(f)[:200]
        self._stop()

    def on_ready(self, conn) -> None:
        self.id_to_name = {v: k for k, v in conn.name_to_id.items()}
        req = ProtoOATraderReq(); req.ctidTraderAccountId = conn.account_id
        conn.client.send(req).addCallbacks(self.on_trader, self._fail)

    def on_trader(self, msg) -> None:
        t = Protobuf.extract(msg).trader
        self.balance = t.balance / (10 ** t.moneyDigits)
        req = ProtoOAReconcileReq(); req.ctidTraderAccountId = self.conn.account_id
        self.conn.client.send(req).addCallbacks(self.on_reconcile, self._fail)

    def on_reconcile(self, msg) -> None:
        for p in Protobuf.extract(msg).position:
            td = p.tradeData
            self.positions.append({
                "id": p.positionId, "symbol": self.id_to_name.get(td.symbolId),
                "side": 1 if td.tradeSide == 1 else -1, "volume": td.volume,
                "label": td.label, "entry": p.price})
        mine = [p for p in self.positions if p["label"] == LABEL and p["symbol"] == SYMBOL]
        if not (self.may_close and mine and mine[0]["side"] != self.want):
            return self._stop()
        self.closing = mine[0]
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.positionId = mine[0]["id"]
        req.volume = mine[0]["volume"]
        self.conn.client.send(req).addCallbacks(self.on_closed, self._fail)

    def on_closed(self, msg) -> None:
        self.closed_id = self.closing["id"]
        reactor.callLater(3, self._stop)         # let the fill land before disconnecting


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    st = load_state()
    today = pd.Timestamp.now(tz="UTC").normalize()
    day = str(today.date())

    if st.get("halted"):
        log_decision({"action": "none", "why": f"halted: {st['halted']}"})
        return 0
    if st.get("decided") == day and not a.dry_run:
        return 0                                   # one decision per day, as tested

    acct = int(settings.ACCOUNT_ID) if settings.ACCOUNT_ID else None
    grant = authority.ensure_standing(acct) if acct else authority.Authority(False, "no account")
    if not grant.permitted and not a.dry_run:
        log_decision({"action": "none", "why": f"no live authority: {grant.reason}"})
        return 1

    subprocess.run([PY, "-m", "market.bars", "--symbol", SYMBOL, "--period", "D1",
                    "--days", "90"], capture_output=True, timeout=300, check=False)
    closes = completed_closes(today)
    want = E.signal(closes)

    b = Broker(want, may_close=not a.dry_run).run()
    if b.balance is None:
        log_decision({"action": "none", "why": f"could not read the account: {b.error}"})
        return 1
    # Two latches from the signed limits: the $20 floor, and the 40% drawdown from the peak.
    # Either one stops the engine for good; only the owner removes the flag.
    st["peak"] = max(float(st.get("peak", 0.0)), b.balance)
    dd = 1.0 - b.balance / st["peak"]
    halt = None
    if b.balance < LIVE_LIMITS.min_equity:
        halt = f"balance ${b.balance:.2f} below the ${LIVE_LIMITS.min_equity:.0f} floor on {day}"
    elif dd >= LIVE_LIMITS.max_drawdown_pct:
        halt = f"drawdown {dd:.0%} from the ${st['peak']:.2f} peak on {day}"
    if halt:
        st["halted"] = halt
        save_state(st)
        log_decision({"action": "HALT", "why": halt})
        return 0

    mine = [p for p in b.positions if p["label"] == LABEL and p["symbol"] == SYMBOL]
    held = mine[0]["side"] if mine else 0
    decision = {"day": day, "signal": want, "held": held, "balance": b.balance,
                "last_close": float(closes.iloc[-1]) if len(closes) else None}
    if a.dry_run:
        log_decision({**decision, "action": "dry-run"})
        return 0
    if mine and held != want:
        if b.closed_id is None:
            log_decision({**decision, "action": "close-failed", "why": b.error})
            return 1
        decision["closed"] = b.closed_id
        held = 0

    if held == 0 and want != 0:
        side = "BUY" if want > 0 else "SELL"
        r = subprocess.run([PY, "-m", "scripts.live_trade", "--symbol", SYMBOL, "--side", side,
                            "--confirm", "--label", LABEL,
                            "--reason", f"E05 20-day trend signal {want:+d} on {day}"],
                           capture_output=True, text=True, timeout=240, check=False)
        tail = [ln for ln in r.stdout.splitlines() if "stages passed" in ln or "  - " in ln]
        decision["opened"] = side
        decision["result"] = " | ".join(tail)[:300]
        action = "open"
    else:
        action = "hold" if held == want and want != 0 else "flat"
    st["decided"] = day
    save_state(st)
    log_decision({**decision, "action": action})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
