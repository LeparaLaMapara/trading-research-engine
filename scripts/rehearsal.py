"""The dress rehearsal: make the engine walk the WHOLE path by itself, on demo.

Why this exists. The research half of this system is real: it ingests years of data across
asset classes, refuses, refits without lookahead, deflates against an honest trial count, and
remembers. The execution half did not exist. Trace a passing candidate and the path ended in
a print statement. `RiskOfficer.permit()` was called in exactly one place and that place was a
test. Nothing sized a position. Nothing managed one.

So every component below is running for the first time, and on this project every component
that ran for the first time had a defect in it: the failure registry vetoed its own search
space, the workflow could not fail, the tick logger looked identical alive and dead, a safety
guard failed silently, and a grid ceiling invented an edge. There is no reason to expect
untested execution code to be different. Far better to find out here.

THE STRATEGY IS DELIBERATELY WORTHLESS. A coin flip on a fixed seed. The gate is lowered on
purpose so something passes. This proves the MACHINERY, not an edge, and any P&L it produces
is noise. Reading it as a result would be the exact error this whole project is built to
avoid.

Hard safety, in layers:
  * DEMO ONLY, confirmed from the broker's own account list, never from CTRADER_ENV.
  * The risk layer is handed demo-stamped limits and refuses a live account by construction.
  * LIVE_LIMITS remains unconfigured, so the live path denies through the same mechanism.
  * Every position is opened WITH a stop and a target attached to the order itself, so a
    dropped connection cannot leave an unmanaged position.
  * One position at a time, and the run closes anything it opened before exiting.

Run:  python -m scripts.rehearsal --confirm
      python -m scripts.rehearsal              # dry run: decides and sizes, sends nothing
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAClosePositionReq,
    ProtoOAExecutionEvent,
    ProtoOAExpectedMarginReq,
    ProtoOANewOrderReq,
    ProtoOAOrderErrorEvent,
    ProtoOAReconcileReq,
    ProtoOASubscribeSpotsReq,
    ProtoOATraderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
)
from twisted.internet import reactor

from connection.client import CTraderConnection
from execution.sizing import SymbolSpec, size_position, stop_and_target
from ledger.trade_log import TradeLog
from risk.limits import DEMO_REHEARSAL_LIMITS, RiskOfficer

EXEC_ORDER_ACCEPTED = 2
EXEC_ORDER_FILLED = 3
POSITION_CLOSED = 2          # ProtoOAPositionStatus.POSITION_STATUS_CLOSED

STOP_PIPS = 20.0
REWARD_RATIO = 1.5
HOLD_TIMEOUT_S = 180          # close it ourselves rather than leave it running
STAGES: list[tuple[str, bool, str]] = []


def stage(name: str, ok: bool, detail: str = "") -> None:
    STAGES.append((name, ok, detail))
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""),
          flush=True)


def decide(seed: int) -> str:
    """The 'strategy'. A coin flip, and it is meant to be.

    Kept honest by being obviously worthless: nobody can mistake this for an edge, which is
    exactly what a rehearsal of the machinery needs.
    """
    return "BUY" if random.Random(seed).random() < 0.5 else "SELL"


class Rehearsal:
    def __init__(self, symbol: str, confirm: bool) -> None:
        self.symbol = symbol.upper()
        self.confirm = confirm
        self.spec = None
        self.symbol_id = None
        self.equity = None
        self.margin_min = None
        self.bid = self.ask = None
        self.position_id = None
        self.entry_price = None
        self.opened_at = None
        self.log = TradeLog()
        self.conn = CTraderConnection(on_ready=self.on_ready, on_spot=self.on_spot,
                                      on_symbol_spec=self.on_spec)
        self._steps: list = []
        self._closing = False
        self._verified = False
        self._unprotected = False

    # ------------------------------------------------------------------ plumbing

    def run(self) -> None:
        self.conn.run()

    def next_step(self) -> None:
        if self._steps:
            self._steps.pop(0)()

    def _send(self, req, on_ok):
        def cb(msg):
            try:
                on_ok(msg)
            except Exception as exc:  # noqa: BLE001
                stage("unexpected error", False, f"{type(exc).__name__}: {exc}")
                self.finish()
                return
            self.next_step()

        def err(f):
            stage("request failed", False, str(f)[:110])
            self.finish()
        self.conn.client.send(req).addCallbacks(cb, err)

    def on_spec(self, sym) -> None:
        self.spec = SymbolSpec(name=self.symbol, min_volume=int(sym.minVolume),
                               step_volume=int(sym.stepVolume), max_volume=int(sym.maxVolume),
                               lot_size=int(sym.lotSize),
                               pip_size=10 ** -sym.pipPosition, digits=int(sym.digits))

    def on_spot(self, ev) -> None:
        if getattr(ev, "bid", 0):
            self.bid = ev.bid / 100000.0
        if getattr(ev, "ask", 0):
            self.ask = ev.ask / 100000.0

    # ------------------------------------------------------------------ the walk

    def on_ready(self, conn) -> None:
        print(f"\n--- rehearsal on {self.symbol} "
              f"({'LIVE ORDER WILL BE SENT' if self.confirm else 'dry run'}) ---\n")
        self.symbol_id = conn.name_to_id.get(self.symbol)
        if not self.symbol_id:
            stage("find the symbol", False, "not on this account")
            return self.finish()
        stage("connect and authenticate", True, f"account {conn.account_id}")

        # THE safety gate. Ask the broker, never the configuration.
        demo = None
        for a in getattr(conn, "accounts", []) or []:
            if a.ctidTraderAccountId == conn.account_id:
                demo = not a.isLive
        if demo is None:
            stage("confirm this is a DEMO account", False, "broker did not say; refusing")
            return self.finish()
        if not demo:
            stage("confirm this is a DEMO account", False,
                  "this is a LIVE account. The rehearsal never runs on live. Refusing.")
            return self.finish()
        stage("confirm this is a DEMO account", True, "broker reports DEMO")

        self._steps = [self.step_account, self.step_spec, self.step_quote, self.step_margin,
                       self.step_decide_and_size, self.step_risk, self.step_place]
        self.next_step()

    def step_account(self) -> None:
        req = ProtoOATraderReq(); req.ctidTraderAccountId = self.conn.account_id

        def ok(msg):
            t = Protobuf.extract(msg).trader
            self.equity = t.balance / (10 ** t.moneyDigits)
            stage("read equity from the broker", True, f"${self.equity:,.2f}")
        self._send(req, ok)

    def step_spec(self) -> None:
        # Poll for the answer rather than sleeping a fixed 3 seconds. The fixed wait passed
        # twice and then failed ("no spec") on a busier run: a timing assumption dressed up
        # as a check. Waiting for the thing you need is not the same as waiting a while.
        self.conn.fetch_symbol_specs([self.symbol_id])
        self._wait_for(lambda: self.spec is not None, 15,
                       "read the symbol's tradable limits",
                       lambda: f"min {self.spec.min_volume/self.spec.lot_size:g} lots")

    def _wait_for(self, predicate, timeout_s: float, label: str, detail=None,
                  _started: float | None = None) -> None:
        started = _started or time.time()
        if predicate():
            stage(label, True, detail() if detail else "")
            return self.next_step()
        if time.time() - started >= timeout_s:
            stage(label, False, f"still not available after {timeout_s:.0f}s")
            return self.finish()
        reactor.callLater(0.25, self._wait_for, predicate, timeout_s, label, detail, started)

    def step_quote(self) -> None:
        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId.append(self.symbol_id)
        self.conn.client.send(req)
        self._wait_for(lambda: self.ask is not None and self.bid is not None, 30,
                       "get a live quote", lambda: f"bid {self.bid} ask {self.ask}")

    def step_margin(self) -> None:
        req = ProtoOAExpectedMarginReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId = self.symbol_id
        req.volume.append(int(self.spec.min_volume))

        def ok(msg):
            res = Protobuf.extract(msg)
            d = getattr(res, "moneyDigits", 2) or 2
            for em in res.margin:
                self.margin_min = em.buyMargin / (10 ** d)
                stage("ask the broker for margin", True,
                      f"${self.margin_min:,.2f} per minimum size")
                return
            stage("ask the broker for margin", False, "no margin returned")
        self._send(req, ok)

    def step_decide_and_size(self) -> None:
        self.side = decide(seed=int(time.time()) // 3600)
        stage("decide (worthless coin flip, on purpose)", True, self.side)
        self.sizing = size_position(self.equity, DEMO_REHEARSAL_LIMITS.max_risk_per_trade_pct,
                                    STOP_PIPS, self.spec, margin_per_min_volume=self.margin_min)
        stage("size the position", self.sizing.allowed,
              f"{self.sizing.lots:g} lots, risks ${self.sizing.risk_amount:,.2f} "
              f"({self.sizing.risk_fraction_actual*100:.2f}%)" if self.sizing.allowed
              else self.sizing.reason)
        if not self.sizing.allowed:
            self.finish()
            return
        self.next_step()

    def step_risk(self) -> None:
        req = ProtoOAReconcileReq(); req.ctidTraderAccountId = self.conn.account_id

        def ok(msg):
            res = Protobuf.extract(msg)
            officer = RiskOfficer(DEMO_REHEARSAL_LIMITS)
            d = officer.permit(account_environment="demo", equity=self.equity,
                               risk_amount=self.sizing.risk_amount,
                               margin_required=self.sizing.margin_required,
                               open_positions=len(res.position),
                               realised_pnl_today=0.0, equity_peak=self.equity)
            stage("risk layer decides", d.allowed, d.reason)
            self.permitted = d.allowed
            if not d.allowed:
                self.finish()
        self._send(req, ok)

    def step_place(self) -> None:
        entry = self.ask if self.side == "BUY" else self.bid
        sl, tp = stop_and_target(entry, self.side, STOP_PIPS, self.spec, REWARD_RATIO)
        pp = round(self.spec.pip_size / (10 ** -self.spec.digits))
        stage("build the order with stop and target", True,
              f"{self.side} {self.sizing.lots:g} lots @ ~{entry}, stop {sl} "
              f"({int(STOP_PIPS*pp)} pts), target {tp} ({int(STOP_PIPS*REWARD_RATIO*pp)} pts)")
        if not self.confirm:
            stage("send the order", True, "DRY RUN - nothing sent. Re-run with --confirm.")
            return self.finish()

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId = self.symbol_id
        req.orderType = ProtoOAOrderType.Value("MARKET")
        req.tradeSide = ProtoOATradeSide.Value(self.side)
        req.volume = int(self.sizing.volume)
        # Stop and target travel WITH the order. A dropped connection must never leave an
        # unmanaged position open.
        #
        # RELATIVE, not absolute. The first version set `stopLoss`/`takeProfit` to absolute
        # prices and the broker silently ignored both: the position filled with stop 0.0 and
        # target 0.0, i.e. completely unprotected, while the order itself reported success.
        # For a MARKET order cTrader takes the distance in POINTS via relativeStopLoss /
        # relativeTakeProfit. One point is 10^-digits, so a pip on a 5-digit symbol is 10
        # points.
        points_per_pip = round(self.spec.pip_size / (10 ** -self.spec.digits))
        req.relativeStopLoss = int(STOP_PIPS * points_per_pip)
        req.relativeTakeProfit = int(STOP_PIPS * REWARD_RATIO * points_per_pip)
        req.label = "rehearsal"
        req.comment = "dress rehearsal, machinery test, not a strategy"
        self.opened_at = time.time()
        self.conn.client.send(req)
        reactor.callLater(HOLD_TIMEOUT_S, self.timeout_close)

    # ------------------------------------------------------------------ live events

    def handle_execution(self, msg) -> None:
        res = Protobuf.extract(msg)
        et = res.executionType
        pos = res.position if res.HasField("position") else None

        # THE BUG THIS REHEARSAL WAS BUILT TO FIND. The first version read
        # `et in (3, 4)` as "closed or partially closed". In fact 3 is ORDER_FILLED and 4 is
        # ORDER_REPLACED. So ORDER_ACCEPTED (2, prices still zero) was logged as "position
        # open", the actual FILL was logged as "position closed", nothing was ever closed,
        # and the run exited 12/12 with a 50-lot position live on the account.
        #
        # A close is a property of the POSITION, not of the execution type. Read it there.
        if pos and pos.positionStatus == POSITION_CLOSED and self.position_id:
            return self.on_closed(res)

        if et == EXEC_ORDER_FILLED and pos and pos.positionId and not self.position_id:
            self.position_id = pos.positionId
            self.entry_price = pos.price
            stage("order filled, position open", True,
                  f"position {self.position_id} at {self.entry_price}, "
                  f"stop {pos.stopLoss}, target {pos.takeProfit}")
            # DO NOT judge protection from this event. The ORDER_FILLED execution event
            # does not carry the stop and target, and reading 0.0 here led to the wrong
            # conclusion that positions were opening unprotected. scripts/stop_probe.py
            # settled it: relative points DO attach, and the broker's own position record
            # shows them. Ask the broker, in verify_protection below.
            reactor.callLater(3, self.verify_protection)
            # A live subclass (scripts/live_trade.py) logs its own fill with the right purpose;
            # this row labelled every live fill "dress rehearsal" until 2026-09-23.
            if getattr(self, "LOGS_OWN_FILLS", False):
                return
            self.log.record(ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"), symbol=self.symbol,
                            side=self.side, order_type="MARKET",
                            volume_lots=self.sizing.lots, filled_price=self.entry_price,
                            stop_loss=res.position.stopLoss,
                            take_profit=res.position.takeProfit,
                            status="FILLED", purpose="rehearsal",
                            note="dress rehearsal open leg")

    def handle_order_error(self, msg) -> None:
        res = Protobuf.extract(msg)
        stage("order rejected by the broker", False,
              f"{res.errorCode}: {getattr(res, 'description', '')}")
        self.log.record(ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"), symbol=self.symbol,
                        side=self.side, order_type="MARKET", status="REJECTED",
                        purpose=getattr(self, "LOG_PURPOSE", "rehearsal"),
                        note=f"order error: {res.errorCode}")
        self.finish()

    def on_closed(self, res) -> None:
        deal = res.deal if res.HasField("deal") else None
        px = deal.executionPrice if deal and deal.HasField("executionPrice") else None
        stage("position closed", True, f"exit {px}")
        self.log.record(ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"), symbol=self.symbol,
                        side="SELL" if self.side == "BUY" else "BUY", order_type="MARKET",
                        filled_price=px, status="CLOSED", purpose="rehearsal",
                        note="dress rehearsal close leg")
        self.finish()

    def verify_protection(self) -> None:
        """Ask the BROKER whether the open position actually carries a stop.

        This is the third time on this project that trusting an event instead of asking the
        broker produced a wrong answer, so the rule is now explicit: protection is a fact
        about the position, and only the position record can state it.
        """
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.conn.account_id

        def ok(msg):
            res = Protobuf.extract(msg)
            mine = [p for p in res.position if p.positionId == self.position_id]
            if not mine:
                stage("stop and target attached (asked the broker)", False,
                      "position not found when checking protection")
                self._unprotected = True
                return
            p = mine[0]
            # The STOP is the protection. A target is required only when the rule sets one;
            # E07 (no target) would otherwise be closed as "unprotected" seconds after opening.
            needs_target = getattr(self, "require_target", True)
            protected = bool(p.stopLoss) and (bool(p.takeProfit) or not needs_target)
            stage("stop and target attached (asked the broker)", protected,
                  f"stop {p.stopLoss}, target {p.takeProfit}" if protected
                  else f"UNPROTECTED: stop {p.stopLoss}, target {p.takeProfit}. "
                       f"This blocks live trading.")
            self._unprotected = not protected

        def err(f):
            stage("stop and target attached (asked the broker)", False,
                  f"could not check: {str(f)[:70]}. Assume unprotected.")
            self._unprotected = True
        self.conn.client.send(req).addCallbacks(ok, err)

    def timeout_close(self) -> None:
        if self.position_id and not self._closing:
            self._closing = True
            stage("hold timeout reached, closing", True, f"after {HOLD_TIMEOUT_S}s")
            req = ProtoOAClosePositionReq()
            req.ctidTraderAccountId = self.conn.account_id
            req.positionId = self.position_id
            req.volume = int(self.sizing.volume)
            self.conn.client.send(req)
            reactor.callLater(20, self.finish)
        elif not self.position_id:
            stage("no fill within the timeout", False, "nothing to close")
            self.finish()

    def finish(self) -> None:
        """Never exit on the strength of our own event handling. ASK the broker."""
        if self._verified or not self.confirm:
            if reactor.running:
                reactor.stop()
            return
        self._verified = True
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.conn.account_id

        def ok(msg):
            res = Protobuf.extract(msg)
            open_n = len(res.position)
            if open_n:
                ids = [p.positionId for p in res.position]
                stage("VERIFY FLAT before declaring success", False,
                      f"{open_n} position(s) STILL OPEN: {ids}. Closing them now.")
                for p in res.position:
                    c = ProtoOAClosePositionReq()
                    c.ctidTraderAccountId = self.conn.account_id
                    c.positionId = p.positionId
                    c.volume = p.tradeData.volume
                    self.conn.client.send(c)
                reactor.callLater(15, lambda: reactor.running and reactor.stop())
            else:
                stage("VERIFY FLAT before declaring success", True, "nothing open")
                if reactor.running:
                    reactor.stop()

        def err(f):
            stage("VERIFY FLAT before declaring success", False,
                  f"could not check: {str(f)[:80]}. Assume something is open.")
            if reactor.running:
                reactor.stop()
        self.conn.client.send(req).addCallbacks(ok, err)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--confirm", action="store_true",
                   help="actually send the order (demo account only, enforced)")
    a = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    r = Rehearsal(a.symbol, a.confirm)
    original = r.conn._on_message

    def dispatch(client, message):
        pt = message.payloadType
        if pt == ProtoOAExecutionEvent().payloadType:
            r.handle_execution(message)
        elif pt == ProtoOAOrderErrorEvent().payloadType:
            r.handle_order_error(message)
        original(client, message)

    r.conn.client.setMessageReceivedCallback(dispatch)
    r.run()

    failed = [s for s in STAGES if not s[1]]
    print(f"\n{len(STAGES) - len(failed)}/{len(STAGES)} stages completed")
    if failed:
        print("stages that failed:")
        for n, _, d in failed:
            print(f"  - {n}: {d}")
    print("\nReminder: the strategy was a coin flip. Any P&L here is noise and means nothing.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
