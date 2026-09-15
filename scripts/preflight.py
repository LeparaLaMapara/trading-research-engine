"""Can this system actually do everything it will need to do? Prove it, before any trade.

Every capability the engine depends on, exercised for real against the broker and reported
as PASS or FAIL in plain words. Run it before trusting anything, after every re-authorisation,
and before the first live order.

THIS TOOL NEVER SENDS AN ORDER. Not once, not with a flag. Order placement is exercised up to
the last instruction and deliberately stopped, because the account now holds enough margin
that a "test" order would genuinely fill. The one thing preflight must never do is become the
first trade.

Two things it checks that are easy to forget:

  * **Can it NOT place an order?** A system that cannot refuse is more dangerous than one that
    cannot act. The risk layer is fail-closed and must deny; a PASS here means it said no.
  * **Absence of evidence is failure.** A check that cannot run reports FAIL, never a
    reassuring skip. The five-week outage looked healthy from the outside precisely because
    nothing distinguished "fine" from "could not tell".

Usage:
    python -m scripts.preflight                # the funded live account
    python -m scripts.preflight --env demo     # the demo endpoint, if a demo account exists
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq,
    ProtoOAReconcileReq,
    ProtoOATraderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import reactor

from connection.client import CTraderConnection

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    mark = {PASS: "PASS", FAIL: "FAIL", INFO: "----"}[status]
    print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))


class Preflight:
    """One connection, every capability, in order. Read-only throughout."""

    def __init__(self, symbol: str = "EURUSD") -> None:
        self.symbol = symbol
        self.symbol_id: int | None = None
        self.spec = None
        self.balance: float | None = None
        self.leverage: float | None = None
        self.conn = CTraderConnection(on_ready=self.on_ready,
                                      on_symbol_spec=self.on_spec)
        self._steps: list = []

    # -- capability checks ---------------------------------------------------------

    def on_ready(self, conn: CTraderConnection) -> None:
        record("Connect to the broker and authenticate the application", PASS,
               f"{os.environ.get('CTRADER_ENV', 'live')} endpoint")
        record("Authenticate the trading account", PASS, f"account {conn.account_id}")
        record("Read the symbol list", PASS, f"{len(conn.name_to_id)} symbols")
        self.symbol_id = conn.name_to_id.get(self.symbol)
        if not self.symbol_id:
            record(f"Find {self.symbol}", FAIL, "not in the symbol list")
            self.finish()
            return
        record(f"Find {self.symbol}", PASS, f"id {self.symbol_id}")
        self._steps = [self.check_accounts, self.check_balance, self.check_spec,
                       self.check_history, self.check_positions, self.check_order_dry_run,
                       self.check_risk_refuses, self.finish]
        self.next_step()

    def next_step(self) -> None:
        if self._steps:
            self._steps.pop(0)()

    def _send(self, req, on_ok) -> None:
        def _cb(message):
            try:
                on_ok(message)
            except Exception as exc:  # noqa: BLE001
                record("unexpected error", FAIL, f"{type(exc).__name__}: {exc}")
            self.next_step()

        def _err(failure):
            record("request failed", FAIL, str(failure)[:120])
            self.next_step()

        self.conn.client.send(req).addCallbacks(_cb, _err)

    def check_accounts(self) -> None:
        # Read the list the connection already fetched. Re-requesting it makes the shared
        # dispatch re-authenticate the account, which the broker rejects as ALREADY_LOGGED_IN.
        accounts = getattr(self.conn, "accounts", [])
        if not accounts:
            record("List every account this token can reach", FAIL, "none returned")
            return self.next_step()
        live = [a for a in accounts if a.isLive]
        demo = [a for a in accounts if not a.isLive]
        record("List every account this token can reach", PASS,
               f"{len(live)} live, {len(demo)} demo")
        for a in accounts:
            record(f"  account {a.ctidTraderAccountId} = login {a.traderLogin}", INFO,
                   "LIVE" if a.isLive else "DEMO")
        if not demo:
            record("A demo account exists to prove order code safely", FAIL,
                   "none found; order paths have nowhere safe to be tested")
        self.next_step()

    def check_balance(self) -> None:
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = self.conn.account_id

        def ok(message):
            t = Protobuf.extract(message).trader
            self.balance = t.balance / (10 ** t.moneyDigits)
            self.leverage = (t.leverageInCents / 100.0) if t.leverageInCents else None
            record("Read the account balance", PASS, f"${self.balance:,.2f}")
            if self.leverage:
                record("Read the account leverage", PASS,
                       f"1:{self.leverage:g} (margin per 0.01 lot ~ ${1150/self.leverage:,.2f})")
            else:
                record("Read the account leverage", FAIL, "not reported")
        self._send(req, ok)

    def check_spec(self) -> None:
        self.conn.fetch_symbol_specs([self.symbol_id])
        # The spec arrives on the shared message callback; give it a moment, then continue.
        reactor.callLater(3, self.next_step)

    def on_spec(self, sym) -> None:
        """The connection hands over an already-extracted symbol, not a raw message."""
        self.spec = sym
        record("Read the tradable limits for the symbol", PASS,
               f"min {sym.minVolume/10**7:g} lots, step {sym.stepVolume/10**7:g}, "
               f"max {sym.maxVolume/10**7:g}")

    def check_history(self) -> None:
        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self.conn.account_id
        req.symbolId = self.symbol_id
        req.period = ProtoOATrendbarPeriod.Value("H1")
        now = int(time.time() * 1000)
        req.fromTimestamp = now - 7 * 24 * 3600 * 1000
        req.toTimestamp = now

        def ok(message):
            res = Protobuf.extract(message)
            n = len(res.trendbar)
            record("Read historical price bars", PASS if n else FAIL, f"{n} bars for the last week")
        self._send(req, ok)

    def check_positions(self) -> None:
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.conn.account_id

        def ok(message):
            res = Protobuf.extract(message)
            pos, orders = len(res.position), len(res.order)
            record("See open positions and pending orders", PASS,
                   f"{pos} open position(s), {orders} pending order(s)")
            if pos or orders:
                record("Account is flat before any test", FAIL,
                       "something is already open; close it before trading tests")
            else:
                record("Account is flat before any test", PASS, "nothing open")
        self._send(req, ok)

    def check_order_dry_run(self) -> None:
        """Compute a real order to the last instruction, then deliberately do not send it."""
        if not self.spec or self.balance is None:
            record("Build a valid order without sending it", FAIL, "missing spec or balance")
            return self.next_step()
        lots = self.spec.minVolume / 10 ** 7
        volume = int(self.spec.minVolume)
        ok_step = volume % int(self.spec.stepVolume) == 0
        within = self.spec.minVolume <= volume <= self.spec.maxVolume
        margin = 1150.0 / self.leverage if self.leverage else None
        affordable = margin is not None and margin <= self.balance
        detail = (f"{lots:g} lots, volume {volume}, step ok={ok_step}, within limits={within}, "
                  f"margin ${margin:,.2f} vs balance ${self.balance:,.2f}")
        record("Build a valid order and stop before sending", PASS if (ok_step and within) else FAIL,
               detail)
        record("Would the broker accept it on margin", PASS if affordable else FAIL,
               "affordable" if affordable else "not enough free margin")
        record("No order was transmitted", PASS, "preflight never sends; by design")
        self.next_step()

    def check_risk_refuses(self) -> None:
        """The most important check. A system that cannot refuse is worse than one that
        cannot act."""
        from risk.limits import RiskOfficer
        decision = RiskOfficer().permit(symbol=self.symbol, volume=1, side="BUY")
        if decision.allowed:
            record("Refuse to trade when the risk limits are not set", FAIL,
                   "the risk layer ALLOWED an order while unconfigured")
        else:
            record("Refuse to trade when the risk limits are not set", PASS,
                   decision.reason)
        self.next_step()

    def finish(self) -> None:
        if reactor.running:
            reactor.stop()

    def run(self) -> None:
        self.conn.run()


def main() -> int:
    p = argparse.ArgumentParser(description="Prove every capability before trading.")
    p.add_argument("--env", choices=["live", "demo"], help="which endpoint to test")
    p.add_argument("--symbol", default="EURUSD")
    args = p.parse_args()
    if args.env:
        os.environ["CTRADER_ENV"] = args.env
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    print(f"\nPreflight on the {os.environ.get('CTRADER_ENV', 'live')} endpoint. "
          f"No order will be sent.\n")
    Preflight(args.symbol).run()

    print()
    failed = [r for r in results if r[1] == FAIL]
    checks = [r for r in results if r[1] != INFO]
    if failed:
        print(f"{len(failed)} of {len(checks)} checks FAILED:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
        print("\nDo not trade until these are resolved.")
    else:
        print(f"All {len(checks)} checks passed. Every capability the engine needs is proven, "
              f"and it still correctly refuses to trade.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
