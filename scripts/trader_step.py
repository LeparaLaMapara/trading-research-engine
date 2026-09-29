"""One decision of the autonomous live trader: the 20-day trend rule, no profit target.

Traded on ETHUSD (E05/E07, label engine-E05) and, from 2026-09-29, on USDSGD (E08, label
engine-E08). With no arguments it steps every instrument in INSTRUMENTS. Each instrument keeps
its own position state; the owner's limits (floor, drawdown, daily loss) are account-wide and
shared. `--blackout` keeps an instrument from trading in the rollover hours, when spreads widen:
E08 passed only just, on costs measured away from the rollover.

E05 went live on 2026-09-23; E07 (the same rule without the 1.5R target) passed the same day
with net Sharpe 0.80 against 0.58 and replaced it for new trades.

Run once an hour by scripts/engine_loop.py. It decides once per COMPLETED daily bar, as the
rule was tested (docs/programme/E05-eth-trend-live-prereg.md). The broker's daily bars close at
21:00 UTC, so the decision lands within an hour of that close (until 2026-09-23 it waited for
the UTC date to change, about 3.5 hours late).

  1. keep the owner's standing grant alive (ops.authority.ensure_standing);
  2. refresh ETHUSD daily bars; the signal uses completed bars only;
  3. read the account, the engine's own positions (label engine-E05) and their live profit, so
     every limit works on EQUITY, not the cash balance;
  4. close the engine's position if the signal disagrees, or to RESIZE it when equity has grown
     by half since it was opened (a deposit, or profits), because size is set only at opening;
  5. if the engine holds nothing, open in the signal's direction through scripts.live_trade.

Limits (the owner's signed numbers, risk/limits.py): a permanent halt at the $20 floor or a
40% drawdown from the equity peak; no new trade on a day already down 10%.

    python -m scripts.trader_step            # live (standing authority)
    python -m scripts.trader_step --dry-run  # decide and print, send nothing
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time

import pandas as pd
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (ProtoOAClosePositionReq,
                                                       ProtoOAGetPositionUnrealizedPnLReq,
                                                       ProtoOAReconcileReq, ProtoOATraderReq)
from twisted.internet import reactor

from config import settings
from connection.client import CTraderConnection
from lab import eth_trend as E
from ops import authority
from risk.limits import LIVE_LIMITS

SYMBOL, LABEL = "ETHUSD", "engine-E05"   # overridden by --symbol / --label
STATE = "data/engine_state.json"
DECISIONS = "data/engine_decisions.jsonl"
PY = sys.executable
DAY_S = 86400
RESIZE_AT = 1.5          # equity 50% above what it was when the engine's position opened


def sk(key: str) -> str:
    """State key for this instrument. ETHUSD keeps the original names so its state carries on."""
    return key if SYMBOL == "ETHUSD" else f"{SYMBOL}:{key}"


def in_blackout(now: float, window: tuple[int, int] | None) -> bool:
    """True inside [start, end) UTC hours, e.g. (20, 23) is 20:00 to 22:59."""
    if not window:
        return False
    return window[0] <= time.gmtime(now).tm_hour < window[1]


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


def completed_bars(now: float) -> pd.DataFrame:
    """Daily bars that have CLOSED by `now` (a bar is stamped at its open, and lasts a day)."""
    with sqlite3.connect("data/market.db") as c:
        df = pd.read_sql_query("SELECT ts_utc, close FROM bars WHERE symbol=? AND period='D1' "
                               "ORDER BY ts_utc", c, params=(SYMBOL,))
    return df[df["ts_utc"] + DAY_S <= now].reset_index(drop=True)


def limits_check(st: dict, equity: float, day: str) -> tuple[str | None, bool, float]:
    """(permanent halt reason or None, blocked today, P&L so far today). Updates `st`."""
    st["peak"] = max(float(st.get("peak", 0.0)), equity)
    if st.get("day") != day:
        st["day"], st["day_start_equity"] = day, equity
    pnl_today = equity - float(st["day_start_equity"])
    if equity < LIVE_LIMITS.min_equity:
        return f"equity ${equity:.2f} below the ${LIVE_LIMITS.min_equity:.0f} floor on {day}", \
            True, pnl_today
    dd = 1.0 - equity / st["peak"]
    if dd >= LIVE_LIMITS.max_drawdown_pct:
        return f"drawdown {dd:.0%} from the ${st['peak']:.2f} peak on {day}", True, pnl_today
    blocked = pnl_today <= -LIVE_LIMITS.max_daily_loss_pct * float(st["day_start_equity"])
    return None, blocked, pnl_today


def should_close(pos: dict | None, want: int, equity: float, opened_equity: float | None) -> str | None:
    """Why the engine's position should be closed now, or None to keep it."""
    if pos is None:
        return None
    if pos["side"] != want:
        return "signal changed"
    if opened_equity and equity >= RESIZE_AT * opened_equity:
        return f"resize: equity ${equity:.2f} vs ${opened_equity:.2f} at opening"
    return None


class Broker:
    """One connection: balance, positions, their live profit; then close the engine's position
    if `policy` says so. Twisted's reactor cannot restart in one process, so it is one run."""

    def __init__(self, policy=None):
        self.policy = policy
        self.balance, self.positions, self.error = None, [], None
        self.unrealised, self.closed_id, self.close_reason = 0.0, None, None
        self.conn = CTraderConnection(on_ready=self.on_ready)

    @property
    def equity(self) -> float | None:
        return None if self.balance is None else self.balance + self.unrealised

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
        req = ProtoOAGetPositionUnrealizedPnLReq(); req.ctidTraderAccountId = self.conn.account_id
        self.conn.client.send(req).addCallbacks(self.on_pnl, self._fail)

    def on_pnl(self, msg) -> None:
        res = Protobuf.extract(msg)
        m = 10 ** (res.moneyDigits or 2)
        self.unrealised = sum(p.netUnrealizedPnL for p in res.positionUnrealizedPnL) / m
        mine = self.mine()
        reason = self.policy(mine, self.equity) if self.policy else None
        if not reason:
            return self._stop()
        self.close_reason = reason
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.positionId, req.volume = mine["id"], mine["volume"]
        self.conn.client.send(req).addCallbacks(self.on_closed, self._fail)

    def mine(self) -> dict | None:
        m = [p for p in self.positions if p["label"] == LABEL and p["symbol"] == SYMBOL]
        return m[0] if m else None

    def on_closed(self, msg) -> None:
        self.closed_id = self.mine()["id"]
        reactor.callLater(3, self._stop)         # let the fill land before disconnecting


#: Every live instrument: (symbol, label, blackout UTC hours or None, record spread first).
#: Run with no --symbol, trader_step steps each one in its own process (Twisted's reactor
#: cannot restart in one process), so the long-running engine loop picks up a new instrument
#: without a restart.
INSTRUMENTS = (
    ("ETHUSD", "engine-E05", None, False),
    # E08 passed on an ASSUMED spread; five minutes of quotes every hour, across every hour
    # of the week including the rollover, turn it into a measurement.
    ("USDSGD", "engine-E08", "20-23", True),
)
SPREAD_S = 300


def run_all() -> int:
    worst = 0
    for sym, label, blackout, record in INSTRUMENTS:
        if record:
            try:
                subprocess.run([PY, "-m", "telemetry.logger", "--symbols", sym, "--duration",
                                str(SPREAD_S), "--no-snapshot"], capture_output=True,
                               timeout=SPREAD_S + 120, check=False)
            except subprocess.TimeoutExpired:
                print(json.dumps({"symbol": sym, "note": "spread recording timed out"}))
        args = [PY, "-m", "scripts.trader_step", "--symbol", sym, "--label", label,
                *(["--blackout", blackout] if blackout else [])]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=400, check=False)
            out = r.stdout.strip().splitlines()
            print(out[-1] if out else json.dumps({"symbol": sym, "note": "no output"}))
            worst = max(worst, r.returncode)
        except subprocess.TimeoutExpired:
            print(json.dumps({"symbol": sym, "note": "trader step timed out"}))
            worst = 1
    return worst


def main() -> int:
    if len(sys.argv) == 1:
        return run_all()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbol", default="ETHUSD")
    ap.add_argument("--label", default="engine-E05")
    ap.add_argument("--blackout", default=None,
                    help="UTC hours with no trading, e.g. 20-23 (start inclusive, end exclusive)")
    a = ap.parse_args()
    global SYMBOL, LABEL
    SYMBOL, LABEL = a.symbol.upper(), a.label
    window = tuple(int(x) for x in a.blackout.split("-")) if a.blackout else None
    st = load_state()
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))

    if st.get("halted"):
        log_decision({"action": "none", "why": f"halted: {st['halted']}"})
        return 0

    acct = int(settings.ACCOUNT_ID) if settings.ACCOUNT_ID else None
    grant = authority.ensure_standing(acct) if acct else authority.Authority(False, "no account")
    if not grant.permitted and not a.dry_run:
        log_decision({"action": "none", "why": f"no live authority: {grant.reason}"})
        return 1

    subprocess.run([PY, "-m", "market.bars", "--symbol", SYMBOL, "--period", "D1",
                    "--days", "90"], capture_output=True, timeout=300, check=False)
    bars = completed_bars(now)
    if bars.empty:
        log_decision({"action": "none", "why": "no completed daily bars"})
        return 1
    bar_ts = int(bars["ts_utc"].iloc[-1])
    new_bar = st.get(sk("decided_bar")) != bar_ts
    if new_bar and in_blackout(now, window):
        # Neither open nor flip at the rollover. The bar stays undecided, so the next hourly
        # step after the window takes the decision.
        log_decision({"symbol": SYMBOL, "action": "wait", "why": f"rollover window {a.blackout} UTC"})
        return 0
    want = E.signal(bars["close"])

    # Decide closing inside the one broker session: on a new bar (signal check) always; between
    # bars only to resize. The limits are evaluated first, on equity.
    verdict = {}

    def policy(mine, equity):
        halt, blocked, pnl = limits_check(st, equity, day)
        verdict.update(halt=halt, blocked=blocked, pnl=pnl)
        if halt or a.dry_run:
            return None
        why = should_close(mine, want if new_bar else (mine or {}).get("side", want), equity,
                           st.get(sk("opened_equity")))
        if why and why.startswith("resize") and (blocked or want == 0):
            return None                  # never resize into a day already at its loss limit
        return why

    b = Broker(policy).run()
    if b.balance is None:
        log_decision({"action": "none", "why": f"could not read the account: {b.error}"})
        return 1
    eq = b.equity
    decision = {"symbol": SYMBOL, "bar": time.strftime("%Y-%m-%d", time.gmtime(bar_ts + DAY_S)), "signal": want,
                "balance": round(b.balance, 2), "equity": round(eq, 2),
                "pnl_today": round(verdict.get("pnl", 0.0), 2)}
    if verdict.get("halt"):
        st["halted"] = verdict["halt"]
        save_state(st)
        log_decision({**decision, "action": "HALT", "why": verdict["halt"]})
        return 0
    mine = b.mine()
    held = mine["side"] if mine else 0
    decision["held"] = held
    if a.dry_run:
        log_decision({**decision, "action": "dry-run",
                      "would_close": should_close(mine, want, eq, st.get(sk("opened_equity")))})
        return 0
    if b.close_reason:
        if b.closed_id is None:
            save_state(st)
            log_decision({**decision, "action": "close-failed", "why": b.error})
            return 1
        decision["closed"], decision["close_reason"] = b.closed_id, b.close_reason
        from ledger.trade_log import TradeLog
        TradeLog("data/trade_log.db").record(
            ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"), symbol=SYMBOL,
            side="SELL" if mine["side"] > 0 else "BUY", order_type="MARKET",
            position_id=str(b.closed_id), status="CLOSED", purpose="live_research_trade",
            note=f"engine close ({b.close_reason}); price and P&L in the broker deal list")
        held = 0
        st.pop(sk("opened_equity"), None)

    if not new_bar and not b.close_reason:
        save_state(st)                   # between bars with nothing to do: stay quiet
        return 0
    action = "hold" if held else "flat"
    if held == 0 and want != 0:
        if verdict.get("blocked"):
            action = "skip: down 10% today"
        else:
            side = "BUY" if want > 0 else "SELL"
            r = subprocess.run(
                [PY, "-m", "scripts.live_trade", "--symbol", SYMBOL, "--side", side, "--confirm",
                 "--no-target", "--label", LABEL, "--pnl-today", f"{verdict.get('pnl', 0.0):.2f}",
                 "--equity-peak", f"{st.get('peak', eq):.2f}",
                 "--reason", f"20-day trend, no target ({LABEL}), signal {want:+d}, "
                             f"bar {decision['bar']}"],
                capture_output=True, text=True, timeout=240, check=False)
            tail = [ln for ln in r.stdout.splitlines() if "stages passed" in ln or "  - " in ln]
            decision["opened"], decision["result"] = side, " | ".join(tail)[:300]
            opened = any("stages passed" in ln and ln.split("/")[0] == ln.split("/")[1].split()[0]
                         for ln in tail)
            if opened:
                st[sk("opened_equity")] = eq
                action = "open"
            else:
                # Not decided: a refused or failed open (a closed market on a Friday night, a
                # lost connection) is retried next hour instead of skipping a whole day.
                save_state(st)
                log_decision({**decision, "action": "open-failed, will retry"})
                return 1
    st[sk("decided_bar")] = bar_ts
    save_state(st)
    log_decision({**decision, "action": action})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
