"""One LIVE trade, from a research signal, through both locks. Dry run by default.

This is the rehearsal's order path (proven on demo: stops attach, closes are verified against
the broker) pointed at the live account, with the three differences that matter:

  * The side comes from a research signal, not a coin flip, and the signal is printed with
    its honest evidence, which is weak (see docs/results/RESULTS-2026-09-19.md).
  * It REQUIRES the owner-signed grant (ops/authority.py) and the owner-approved LIVE_LIMITS
    (risk/limits.py). Neither can be produced from a development session.
  * The position is NOT closed after a few minutes. It carries a broker-side stop and target
    from the moment it opens, so it is protected with nothing running. A time exit is a
    separate step: `python -m scripts.reconcile --close-all`.

The stop is set from the instrument's own recent volatility (STOP_SIGMAS daily sigmas), the
target at REWARD_RATIO times the stop, and the size is whatever the risk limit allows, which
at this account size is the broker minimum or nothing.

Run:  python -m scripts.live_trade --symbol ETHUSD --side BUY            # dry run
      python -m scripts.live_trade --symbol ETHUSD --side BUY --confirm  # live, needs grant
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import time

import numpy as np
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (ProtoOAExecutionEvent, ProtoOANewOrderReq,
                                                       ProtoOAOrderErrorEvent, ProtoOAReconcileReq)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from twisted.internet import reactor

from execution.sizing import size_position
from lab import clock as _clock
from lab.lifecycle import OrderLifecycle
from ops.authority import live_trading_permitted
from risk.limits import LIVE_LIMITS, RiskOfficer
from scripts import rehearsal as R

STOP_SIGMAS = 2.0
REWARD_RATIO = 1.5
ZAR_PER_USD = 18.0          # only for the capital-ceiling comparison; conservative
#: What sizing uses when LIVE_LIMITS is not yet configured, so a DRY RUN can show the trade
#: the owner would be approving. Never reaches the risk gate: that always reads LIVE_LIMITS.
PREVIEW_RISK_PER_TRADE = 0.06


def daily_sigma(symbol: str) -> float:
    """EWMA (span 36) daily return volatility from stored D1 bars, known before the trade."""
    c = sqlite3.connect("data/market.db")
    closes = [r[0] for r in c.execute("SELECT close FROM bars WHERE symbol=? AND period='D1' "
                                      "ORDER BY ts_utc DESC LIMIT 200", (symbol,))][::-1]
    c.close()
    r = np.diff(np.log(closes))
    w = 2.0 / 37.0
    var = r[0] ** 2
    for x in r[1:]:
        var = (1 - w) * var + w * x * x
    return float(math.sqrt(var))


class LiveTrade(R.Rehearsal):
    LOGS_OWN_FILLS = True
    LOG_PURPOSE = "live_research_trade"

    def __init__(self, symbol: str, side: str, confirm: bool, reason: str,
                 label: str = "research-signal", pnl_today: float = 0.0,
                 equity_peak: float | None = None, target: bool = True) -> None:
        super().__init__(symbol, confirm)
        self.side = side
        self.reason = reason
        self.label = label
        # Supplied by the caller (scripts/trader_step.py), which tracks them across days. The
        # officer's daily-loss and drawdown checks were blind without them until 2026-09-23.
        self.pnl_today, self.peak = pnl_today, equity_peak
        # E07 (passed 2026-09-23): no profit target; exits at the stop or on a signal flip.
        self.require_target = target
        self.sigma = daily_sigma(self.symbol)
        # Mission step 4: the order's own timeline, measured rather than assumed.
        self.life = OrderLifecycle(symbol=self.symbol, side=side, strategy="operator_signal")
        off, unc = _clock.consensus(_clock.measure())
        self.life.use_clock(off, unc)
        self.life.mark("signal")

    def on_ready(self, conn) -> None:
        print(f"\n--- LIVE trade on {self.symbol} "
              f"({'ORDER WILL BE SENT' if self.confirm else 'dry run, nothing sent'}) ---")
        print(f"    signal: {self.side}. {self.reason}\n")
        self.symbol_id = conn.name_to_id.get(self.symbol)
        if not self.symbol_id:
            R.stage("find the symbol", False, "not on this account")
            return self.finish()
        R.stage("connect and authenticate", True, f"account {conn.account_id}")

        live = None
        for a in getattr(conn, "accounts", []) or []:
            if a.ctidTraderAccountId == conn.account_id:
                live = bool(a.isLive)
        if live is not True:
            R.stage("confirm this is the LIVE account", False,
                    "broker did not report LIVE; this tool is for the live account only")
            return self.finish()
        R.stage("confirm this is the LIVE account", True, "broker reports LIVE")

        # Lock one. Checked for the dry run too, so the owner can see exactly what is missing.
        auth = live_trading_permitted(account_id=conn.account_id)
        R.stage("owner-signed live authority", auth.permitted, auth.reason)
        if not auth.permitted and self.confirm:
            return self.finish()
        self.auth = auth
        self._steps = [self.step_account, self.step_spec, self.step_quote, self.step_margin,
                       self.step_decide_and_size, self.step_risk, self.step_place]
        self.next_step()

    def step_decide_and_size(self) -> None:
        mid = (self.bid + self.ask) / 2.0
        self.stop_pips = STOP_SIGMAS * self.sigma * mid / self.spec.pip_size
        R.stage("stop from volatility", True,
                f"daily sigma {self.sigma*100:.2f}%, stop {STOP_SIGMAS:g} sigma = "
                f"{self.stop_pips:.0f} pips ({STOP_SIGMAS*self.sigma*100:.2f}% of price)")
        risk_frac = LIVE_LIMITS.max_risk_per_trade_pct
        if risk_frac is None:
            risk_frac = PREVIEW_RISK_PER_TRADE
            R.stage("LIVE_LIMITS not configured", True,
                    f"sizing PREVIEW at {risk_frac*100:.0f}% risk; the risk gate will still deny")
        self.sizing = size_position(self.equity, risk_frac, self.stop_pips, self.spec,
                                    margin_per_min_volume=self.margin_min)
        R.stage("size the position", self.sizing.allowed,
                f"{self.sizing.lots:g} lots, risks ${self.sizing.risk_amount:,.2f} "
                f"({self.sizing.risk_fraction_actual*100:.2f}% of ${self.equity:,.2f}), "
                f"margin ${self.sizing.margin_required or 0:,.2f}" if self.sizing.allowed
                else self.sizing.reason)
        if not self.sizing.allowed:
            return self.finish()
        cap_zar = self.equity * ZAR_PER_USD
        if self.auth.permitted and self.auth.max_capital_zar is not None \
                and cap_zar > self.auth.max_capital_zar:
            R.stage("within the owner's capital ceiling", False,
                    f"account ~R{cap_zar:,.0f} above ceiling R{self.auth.max_capital_zar:,.0f}")
            return self.finish()
        self.next_step()

    def step_risk(self) -> None:
        req = ProtoOAReconcileReq(); req.ctidTraderAccountId = self.conn.account_id
        self.life.mark("risk_start")

        def ok(msg):
            res = Protobuf.extract(msg)
            d = RiskOfficer(LIVE_LIMITS).permit(
                account_environment="live", equity=self.equity,
                risk_amount=self.sizing.risk_amount, margin_required=self.sizing.margin_required,
                open_positions=len(res.position), realised_pnl_today=self.pnl_today,
                equity_peak=max(self.peak or 0.0, self.equity))
            self.life.mark("risk_done")
            R.stage("risk layer decides (LIVE_LIMITS)", d.allowed, d.reason)
            if not d.allowed and self.confirm:
                self.finish()          # a dry run continues so the owner sees the full order
        self._send(req, ok)

    def _relative_points(self, price_distance: float) -> int:
        """cTrader relative stop/target distance, in the API's FIXED 1e-5 price units.

        Learned from a live rejection on 2026-09-20: ETHUSD BUY came back INVALID_REQUEST
        "Relative stop loss has invalid precision". The rehearsal's formula (distance in the
        SYMBOL's own 10^-digits units) is right only when digits == 5, which is why it passed
        on EURUSD and failed on a 2-digit symbol. Prices on this API are scaled by a fixed
        10^5 whatever `digits` says, and the distance must land on the symbol's own tick, so
        it is rounded to a multiple of 10^(5 - digits).
        """
        step = 10 ** max(0, 5 - int(self.spec.digits))
        raw = price_distance * 1e5
        return int(max(round(raw / step), 1) * step)

    def step_place(self) -> None:
        entry = self.ask if self.side == "BUY" else self.bid
        stop_distance = self.stop_pips * self.spec.pip_size
        stop_pts = self._relative_points(stop_distance)
        tp_pts = (self._relative_points(stop_distance * REWARD_RATIO)
                  if self.require_target else None)
        R.stage("build the order with stop and target", True,
                f"{self.side} {self.sizing.lots:g} lots @ ~{entry}, stop {stop_pts} pts, "
                f"target {tp_pts} pts")
        if not self.confirm:
            R.stage("send the order", True, "DRY RUN - nothing sent.")
            return self.finish()
        if not self.auth.permitted:
            R.stage("send the order", False, "no live authority")
            return self.finish()
        self.life.mark("order_created")
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId = self.symbol_id
        req.orderType = ProtoOAOrderType.Value("MARKET")
        req.tradeSide = ProtoOATradeSide.Value(self.side)
        req.volume = int(self.sizing.volume)
        req.relativeStopLoss = stop_pts
        if tp_pts is not None:
            req.relativeTakeProfit = tp_pts
        # The engine recognises its own positions by label (scripts/trader_step.py).
        req.label = self.label
        req.comment = self.reason[:100]
        self.opened_at = time.time()
        self.conn.client.send(req)
        self.life.mark("order_sent")
        # Leave the position open under its broker-side stop and target. Stop the process once
        # protection is verified (verify_protection runs 3s after the fill).
        reactor.callLater(25, self._done_after_protection)

    def _done_after_protection(self) -> None:
        if self.position_id and not self._unprotected:
            R.stage("position left open under broker-side stop and target", True,
                    f"position {self.position_id}")
            if reactor.running:
                reactor.stop()
        elif self.position_id and self._unprotected:
            R.stage("UNPROTECTED position: closing it now", False, "")
            self._closing = True
            self.timeout_close()
        else:
            R.stage("no fill confirmed", False, "check with scripts.reconcile")
            if reactor.running:
                reactor.stop()

    def timeout_close(self) -> None:
        # Only used for an unprotected position. A protected one is left to its stop/target.
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAClosePositionReq
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.positionId = self.position_id
        req.volume = int(self.sizing.volume)
        self.conn.client.send(req)
        reactor.callLater(20, lambda: reactor.stop() if reactor.running else None)


    def handle_execution(self, msg) -> None:
        """Same as the rehearsal, but logged as what it is: a live research trade."""
        res = Protobuf.extract(msg)
        # The broker's OWN stamps: the only way to see the network and matching legs.
        if res.HasField("order") and res.order.HasField("utcLastUpdateTimestamp"):
            self.life.mark("broker_ack", res.order.utcLastUpdateTimestamp / 1000.0)
        if res.HasField("deal"):
            deal = res.deal
            stage = "final_fill" if deal.HasField("executionTimestamp") else "first_fill"
            ts = (deal.executionTimestamp if deal.HasField("executionTimestamp")
                  else deal.createTimestamp) / 1000.0
            self.life.mark(stage, ts)
        super().handle_execution(msg)
        # The broker sends several execution events per order (accepted, filled, stop set).
        # Record the fill once: the first live engine trade was logged twice on 2026-09-23.
        if self.position_id and not getattr(self, "_logged", False):
            self._logged = True
            self.log.record(ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"), symbol=self.symbol,
                            side=self.side, order_type="MARKET",
                            volume_lots=self.sizing.lots, filled_price=self.entry_price,
                            position_id=str(self.position_id), status="FILLED",
                            purpose="live_research_trade", note=self.reason[:200])

    def handle_order_error(self, msg) -> None:
        self.life.mark("rejected")
        super().handle_order_error(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--side", choices=("BUY", "SELL"), required=True)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--label", default="research-signal")
    ap.add_argument("--pnl-today", type=float, default=0.0)
    ap.add_argument("--equity-peak", type=float, default=None)
    ap.add_argument("--no-target", action="store_true", help="stop only (E07)")
    a = ap.parse_args()
    t = LiveTrade(a.symbol, a.side, a.confirm, a.reason, a.label, a.pnl_today, a.equity_peak,
                  target=not a.no_target)
    original = t.conn._on_message

    def dispatch(client, message):
        pt = message.payloadType
        if pt == ProtoOAExecutionEvent().payloadType:
            t.handle_execution(message)
        elif pt == ProtoOAOrderErrorEvent().payloadType:
            t.handle_order_error(message)
        original(client, message)

    t.conn.client.setMessageReceivedCallback(dispatch)
    t.run()
    failed = [x for x in R.STAGES if not x[1]]
    print()
    if t.life.local:
        t.life.persist()
        print(t.life.report())
        print()
    print(f"{len(R.STAGES) - len(failed)}/{len(R.STAGES)} stages passed")
    for n, _, d in failed:
        print(f"  - {n}: {d}")


if __name__ == "__main__":
    main()
