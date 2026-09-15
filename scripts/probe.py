"""Phase 1a-active execution probe -- a MEASUREMENT, not a strategy trade.

Opens the broker-minimum size and closes it immediately (by positionId, so it works on
netting OR hedging accounts) to record the REAL round-trip execution that demo servers
fake: entry/exit slippage, the spread actually paid, commission, swap, and the true
all-in cost taken as the account-balance delta. Every leg is written to the SARS trade
log (purpose='telemetry_probe').

There is NO strategy and NO AI in this path. Direction does not encode a view -- a probe
is bought to learn what execution costs, and it is expected to lose roughly the spread.

Safety model (this is a LIVE account -- real money):
  * DRY RUN BY DEFAULT. Without --confirm it connects, authenticates, captures a live
    quote, prints the exact open+close plan, and sends NOTHING.
  * Minimum volume only.
  * Immediate close, plus a hard timeout that force-closes if the close leg is slow. If a
    position is ever left open, its positionId is printed loudly for manual closure.

Run:
  python -m scripts.probe                     # dry run (EURUSD, buy, minimum lot)
  python -m scripts.probe --confirm           # ACTUALLY open + immediately close
  python -m scripts.probe --side sell --confirm
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAClosePositionReq,
    ProtoOAErrorRes,
    ProtoOAExecutionEvent,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOANewOrderReq,
    ProtoOAOrderErrorEvent,
    ProtoOASpotEvent,
    ProtoOASubscribeSpotsReq,
    ProtoOASubscribeSpotsRes,
    ProtoOASymbolByIdReq,
    ProtoOASymbolByIdRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
    ProtoOATraderReq,
    ProtoOATraderRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAExecutionType,
    ProtoOAOrderType,
    ProtoOATradeSide,
)
from twisted.internet import reactor

from config import settings
from connection import tokens
from ledger.trade_log import TradeLog

HOST = EndPoints.PROTOBUF_LIVE_HOST if settings.ENV == "live" else EndPoints.PROTOBUF_DEMO_HOST
SPOT_SCALE = 1e5            # cTrader spot events are ints at a fixed 1e5 scale
OVERALL_TIMEOUT_S = 45
CLOSE_TIMEOUT_S = 8        # force-close if the position isn't closed this long after opening


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One execution probe: open minimum size, close immediately.")
    p.add_argument("--symbol", default=os.environ.get("SYMBOL_NAME", "EURUSD").upper(),
                   help="symbol name (default: SYMBOL_NAME env or EURUSD)")
    p.add_argument("--side", choices=["buy", "sell"], default="buy",
                   help="open direction (a probe measures cost; direction is not a view)")
    p.add_argument("--confirm", action="store_true",
                   help="ACTUALLY trade. Without this it is a dry run and sends nothing.")
    p.add_argument("--allow-live", action="store_true",
                   help="Permit --confirm against a LIVE account. Without it, a confirmed "
                        "probe aborts unless the BROKER reports the account as demo.")
    p.add_argument("--db", default="data/trade_log.db", help="trade log path")
    return p.parse_args()


ARGS = parse_args()
CONFIRMED = ARGS.confirm


class Probe:
    def __init__(self) -> None:
        self.accounts = []          # filled from the broker; drives the pre-send safety check
        self.client = Client(HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)

        self.access_token: str | None = None
        self.refresh_attempted = False
        self.account_id: int | None = int(settings.ACCOUNT_ID) if settings.ACCOUNT_ID else None
        self.money_digits = 2
        self.balance_before: float | None = None

        self.symbol = None                # full ProtoOASymbol
        self.pip = 0.0001
        self.ref_bid: float | None = None
        self.ref_ask: float | None = None

        self.opened = False               # open order sent
        self.entry_done = False
        self.close_sent = False
        self.close_done = False
        self.position_id: int | None = None
        self.open_volume = 0
        self.entry_price: float | None = None
        self.exit_price: float | None = None
        self.entry_commission = 0.0
        self.gross_pnl: float | None = None
        self.swap = 0.0
        self.close_commission = 0.0
        self.balance_after: float | None = None
        self.request_ts: float | None = None
        self.exit_code = 0

        self.log = TradeLog(ARGS.db)

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> None:
        if not settings.CLIENT_ID or not settings.CLIENT_SECRET:
            print("set CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET first.", file=sys.stderr)
            sys.exit(1)
        self.client.startService()
        reactor.callLater(OVERALL_TIMEOUT_S, self._overall_timeout)
        reactor.run()
        sys.exit(self.exit_code)

    def _stop(self, code: int = 0) -> None:
        self.exit_code = code
        if reactor.running:
            reactor.stop()

    def _on_connected(self, client: Client) -> None:
        print(f"connected to {HOST}:{EndPoints.PROTOBUF_PORT} ({settings.ENV})")
        req = ProtoOAApplicationAuthReq()
        req.clientId = settings.CLIENT_ID
        req.clientSecret = settings.CLIENT_SECRET
        client.send(req)

    def _on_disconnected(self, client: Client, reason: object) -> None:
        # Only alarming if we still hold a position.
        if self.entry_done and not self.close_done:
            print(f"DISCONNECTED WITH POSITION {self.position_id} STILL OPEN: {reason}", file=sys.stderr)
        else:
            print(f"disconnected: {reason}", file=sys.stderr)

    def _err(self, failure: object) -> None:
        print(f"request failed: {failure}", file=sys.stderr)

    # -- helpers -----------------------------------------------------------
    def _money(self, raw: int) -> float:
        return raw / (10 ** self.money_digits)

    def _send_open(self) -> None:
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.account_id
        req.symbolId = self.symbol.symbolId
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if ARGS.side == "buy" else ProtoOATradeSide.SELL
        req.volume = self.open_volume
        print("\nSENDING open (market "
              f"{ARGS.side.upper()} {self.open_volume} vol == "
              f"{self.open_volume / self.symbol.lotSize:g} lots)...")
        self.opened = True
        self.request_ts = time.time()
        self.client.send(req).addErrback(self._err)

    def _send_close(self) -> None:
        if self.position_id is None:
            return
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self.account_id
        req.positionId = self.position_id
        req.volume = self.open_volume
        self.close_sent = True
        print(f"SENDING close of position {self.position_id}...")
        self.client.send(req).addErrback(self._err)

    def _close_timeout(self) -> None:
        if self.entry_done and not self.close_done and not self.close_sent:
            print("close not yet sent; forcing close now.", file=sys.stderr)
            self._send_close()

    def _overall_timeout(self) -> None:
        if self.entry_done and not self.close_done:
            print(f"\n*** TIMEOUT WITH POSITION {self.position_id} STILL OPEN ***\n"
                  f"*** Close it manually in the cTrader app (symbol {ARGS.symbol}, "
                  f"volume {self.open_volume}). ***", file=sys.stderr)
            self._stop(2)
        elif not self.close_done and self.opened:
            print("timeout before close confirmed.", file=sys.stderr)
            self._stop(1)
        else:
            self._stop(self.exit_code)

    # -- plan / dry run ----------------------------------------------------
    def _describe_and_maybe_open(self) -> None:
        s = self.symbol
        lots = self.open_volume / s.lotSize if s.lotSize else 0
        notional_units = self.open_volume / 100.0      # cTrader volume is units*100
        spread_pips = (self.ref_ask - self.ref_bid) / self.pip
        pip_value_acct = self.open_volume / 100.0 * self.pip   # approx quote-ccy value per pip
        print("\n--- probe plan ---")
        print(f"  account        {self.account_id} ({settings.ENV})  balance ${self.balance_before}")
        print(f"  symbol         {ARGS.symbol}  (id={s.symbolId}, digits={s.digits}, pip={self.pip})")
        print(f"  side           {ARGS.side.upper()}  (probe -- direction carries no view)")
        print(f"  volume         {self.open_volume}  == {lots:g} lots  (~{notional_units:g} units notional)")
        print(f"  live quote     bid={self.ref_bid}  ask={self.ref_ask}  spread={spread_pips:.2f} pips")
        print(f"  ~pip value     ~{pip_value_acct:.4f} (quote ccy) per pip on this size")
        print(f"  plan           open at market, then close position immediately")
        if not CONFIRMED:
            print("\nDRY RUN -- nothing sent. Re-run with --confirm to trade.")
            self._stop(0)
            return
        # Belt and braces before anything is transmitted. The account id and the endpoint both
        # come from configuration, and configuration on this project has been wrong more than
        # once (leverage inferred as 1:100 when it was 1:50; an API id mistaken for a login
        # number). So ask the BROKER whether this account is live, rather than trusting
        # CTRADER_ENV, and refuse unless the operator explicitly said live was intended.
        try:
            is_demo = self._broker_says_demo()
        except Exception as exc:  # noqa: BLE001
            print(f"ABORT: safety check failed ({type(exc).__name__}: {exc}). Nothing sent.",
                  file=sys.stderr)
            self._stop(2)
            return
        if is_demo is None:
            print("ABORT: could not confirm from the broker whether this account is demo or "
                  "live. Refusing to send.", file=sys.stderr)
            self._stop(2)
            return
        if not is_demo and not ARGS.allow_live:
            print(f"ABORT: account {self.account_id} is LIVE and --allow-live was not given. "
                  f"Nothing was sent.", file=sys.stderr)
            self._stop(2)
            return
        print("  safety         broker reports this account as "
              + ("DEMO" if is_demo else "LIVE (explicitly allowed)"))
        reactor.callLater(CLOSE_TIMEOUT_S, self._close_timeout)
        self._send_open()

    def _broker_says_demo(self):
        """Ask the account list, not the config. None means we could not tell, and that is
        treated as a refusal rather than as permission.

        Any exception in here returns None too. An earlier version read the wrong attribute,
        raised inside a Twisted callback, and was swallowed whole: no abort, no error, exit
        code 0. It happened to send nothing, but by accident rather than by design. A safety
        check that can fail silently is not a safety check.
        """
        try:
            for a in getattr(self, "accounts", None) or []:
                if a.ctidTraderAccountId == self.account_id:
                    return not a.isLive
        except Exception as exc:  # noqa: BLE001 - refuse on anything unexpected
            print(f"safety check raised {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

    def _record_entry(self, deal) -> None:
        self.entry_price = deal.executionPrice if deal.HasField("executionPrice") else None
        if deal.HasField("commission"):
            self.entry_commission = self._money(deal.commission)
        slippage = None
        if self.entry_price is not None and self.ref_ask is not None:
            ref = self.ref_ask if ARGS.side == "buy" else self.ref_bid
            slippage = (self.entry_price - ref) / self.pip
        self.log.record(
            ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"),
            symbol=ARGS.symbol, side=ARGS.side.upper(), order_type="MARKET",
            volume_lots=self.open_volume / self.symbol.lotSize if self.symbol.lotSize else None,
            requested_price=self.ref_ask if ARGS.side == "buy" else self.ref_bid,
            filled_price=self.entry_price, slippage_pips=slippage,
            commission=self.entry_commission, order_id=None,
            deal_id=deal.dealId if deal.HasField("dealId") else None,
            position_id=self.position_id, status="FILLED",
            purpose="telemetry_probe", note="probe open leg",
        )
        lat = (time.time() - self.request_ts) * 1000 if self.request_ts else None
        print(f"  entry filled   price={self.entry_price}  slippage={slippage:.2f} pips"
              if slippage is not None else f"  entry filled   price={self.entry_price}")
        if lat is not None:
            print(f"  open latency   ~{lat:.0f} ms")

    def _record_close(self, deal) -> None:
        self.exit_price = deal.executionPrice if deal.HasField("executionPrice") else None
        cpd = deal.closePositionDetail if deal.HasField("closePositionDetail") else None
        if cpd is not None:
            self.gross_pnl = self._money(cpd.grossProfit) if cpd.HasField("grossProfit") else None
            self.swap = self._money(cpd.swap) if cpd.HasField("swap") else 0.0
            self.balance_after = self._money(cpd.balance) if cpd.HasField("balance") else None
        if deal.HasField("commission"):
            self.close_commission = self._money(deal.commission)
        net = None
        if self.balance_after is not None and self.balance_before is not None:
            net = round(self.balance_after - self.balance_before, self.money_digits)
        self.log.record(
            ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"),
            symbol=ARGS.symbol, side=("SELL" if ARGS.side == "buy" else "BUY"),
            order_type="MARKET",
            volume_lots=self.open_volume / self.symbol.lotSize if self.symbol.lotSize else None,
            filled_price=self.exit_price, commission=self.close_commission,
            swap=self.swap, gross_pnl=self.gross_pnl, net_pnl=net,
            position_id=self.position_id, status="CLOSED",
            purpose="telemetry_probe", note="probe close leg (round-trip)",
        )
        self.close_done = True

    # -- dispatch ----------------------------------------------------------
    def _on_message(self, client: Client, message: object) -> None:
        pt = message.payloadType
        if self.opened and pt not in (ProtoOAExecutionEvent().payloadType, ProtoOASpotEvent().payloadType):
            print(f"[msg after order] payloadType={pt}")

        if pt == ProtoOAOrderErrorEvent().payloadType:
            res = Protobuf.extract(message)
            print(f"ORDER ERROR: {res.errorCode}: "
                  f"{res.description if res.HasField('description') else ''}", file=sys.stderr)
            self.log.record(ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"),
                            symbol=ARGS.symbol, side=ARGS.side.upper(), order_type="MARKET",
                            status="REJECTED", purpose="telemetry_probe",
                            note=f"order error: {res.errorCode}")
            if self.entry_done and not self.close_done:
                self._send_close()
            else:
                self._stop(1)
            return

        if pt == ProtoOAApplicationAuthRes().payloadType:
            print("application authenticated")
            self.access_token = tokens.access_token()
            if not self.access_token:
                print("no access token; run the ctrader-connect OAuth flow first.", file=sys.stderr)
                self._stop(1)
                return
            req = ProtoOAGetAccountListByAccessTokenReq()
            req.accessToken = self.access_token
            client.send(req).addErrback(self._err)

        elif pt == ProtoOAGetAccountListByAccessTokenRes().payloadType:
            res = Protobuf.extract(message)
            accounts = list(res.ctidTraderAccount)
            # Kept so the pre-send safety check can ask the BROKER whether this account is
            # live. It was being fetched and discarded.
            self.accounts = accounts
            if not accounts:
                print("token grants no trading accounts.", file=sys.stderr)
                self._stop(1)
                return
            if self.account_id is None:
                self.account_id = accounts[0].ctidTraderAccountId
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = self.account_id
            req.accessToken = self.access_token
            client.send(req).addErrback(self._err)

        elif pt == ProtoOAAccountAuthRes().payloadType:
            print(f"account {self.account_id} authenticated")
            req = ProtoOATraderReq()
            req.ctidTraderAccountId = self.account_id
            client.send(req).addErrback(self._err)

        elif pt == ProtoOATraderRes().payloadType:
            t = Protobuf.extract(message).trader
            self.money_digits = t.moneyDigits
            self.balance_before = self._money(t.balance)
            print(f"balance before: ${self.balance_before}")
            req = ProtoOASymbolsListReq()
            req.ctidTraderAccountId = self.account_id
            client.send(req).addErrback(self._err)

        elif pt == ProtoOASymbolsListRes().payloadType:
            res = Protobuf.extract(message)
            match = [s for s in res.symbol if s.symbolName.upper() == ARGS.symbol]
            if not match:
                print(f"symbol {ARGS.symbol} not found.", file=sys.stderr)
                self._stop(1)
                return
            req = ProtoOASymbolByIdReq()
            req.ctidTraderAccountId = self.account_id
            req.symbolId.append(match[0].symbolId)
            client.send(req).addErrback(self._err)

        elif pt == ProtoOASymbolByIdRes().payloadType:
            res = Protobuf.extract(message)
            if not res.symbol:
                print("symbol detail not returned.", file=sys.stderr)
                self._stop(1)
                return
            self.symbol = res.symbol[0]
            self.pip = 10 ** (-self.symbol.pipPosition) if self.symbol.pipPosition else 0.0001
            self.open_volume = self.symbol.minVolume
            req = ProtoOASubscribeSpotsReq()
            req.ctidTraderAccountId = self.account_id
            req.symbolId.append(self.symbol.symbolId)
            client.send(req).addErrback(self._err)

        elif pt == ProtoOASubscribeSpotsRes().payloadType:
            pass   # wait for the first spot

        elif pt == ProtoOASpotEvent().payloadType:
            if self.opened:
                return
            res = Protobuf.extract(message)
            if res.HasField("bid"):
                self.ref_bid = res.bid / SPOT_SCALE
            if res.HasField("ask"):
                self.ref_ask = res.ask / SPOT_SCALE
            if self.ref_bid is not None and self.ref_ask is not None:
                self._describe_and_maybe_open()

        elif pt == ProtoOAExecutionEvent().payloadType:
            res = Protobuf.extract(message)
            if res.executionType == ProtoOAExecutionType.ORDER_REJECTED:
                reason = res.errorCode if res.HasField("errorCode") else "?"
                print(f"ORDER REJECTED: {reason}", file=sys.stderr)
                self.log.record(ts_sast=time.strftime("%Y-%m-%d %H:%M:%S"),
                                symbol=ARGS.symbol, side=ARGS.side.upper(), order_type="MARKET",
                                status="REJECTED", purpose="telemetry_probe",
                                note=f"open rejected: {reason}")
                self._stop(1)
                return
            if res.executionType != ProtoOAExecutionType.ORDER_FILLED:
                return   # ORDER_ACCEPTED etc. -- wait for the fill
            deal = res.deal if res.HasField("deal") else None
            if deal is None:
                return
            if not self.entry_done:
                self.position_id = (res.position.positionId if res.HasField("position")
                                    else (deal.positionId if deal.HasField("positionId") else None))
                self.entry_done = True
                self._record_entry(deal)
                self._send_close()
            elif not self.close_done:
                self._record_close(deal)
                self._report()
                self._stop(0)

        elif pt == ProtoOAErrorRes().payloadType:
            res = Protobuf.extract(message)
            print(f"API error {res.errorCode}: {res.description}", file=sys.stderr)
            if "ACCESS_TOKEN" in res.errorCode and not self.refresh_attempted and not self.opened:
                self.refresh_attempted = True
                print("access token rejected; attempting refresh...", file=sys.stderr)
                try:
                    self.access_token = tokens.refresh()["access_token"]
                    req = ProtoOAGetAccountListByAccessTokenReq()
                    req.accessToken = self.access_token
                    client.send(req).addErrback(self._err)
                except Exception as exc:  # noqa: BLE001
                    print(f"refresh failed: {exc}", file=sys.stderr)
                    self._stop(1)
            elif self.entry_done and not self.close_done:
                print("error after opening; retrying close.", file=sys.stderr)
                self._send_close()
            else:
                self._stop(1)

    def _report(self) -> None:
        rt_pips = None
        if self.entry_price is not None and self.exit_price is not None:
            # cost in pips: for a buy we open at ask, close at bid, so entry-exit reflects spread + moves
            rt_pips = (self.exit_price - self.entry_price) / self.pip
            if ARGS.side == "sell":
                rt_pips = -rt_pips
        net = (round(self.balance_after - self.balance_before, self.money_digits)
               if self.balance_after is not None and self.balance_before is not None else None)
        print("\n--- probe result (REAL execution) ---")
        print(f"  entry price    {self.entry_price}")
        print(f"  exit price     {self.exit_price}")
        if rt_pips is not None:
            print(f"  round-trip     {rt_pips:.2f} pips (price move over the hold, your side)")
        print(f"  commission     open {self.entry_commission} + close {self.close_commission}")
        print(f"  swap           {self.swap}")
        print(f"  gross P&L      {self.gross_pnl}")
        print(f"  balance        ${self.balance_before}  ->  ${self.balance_after}")
        print(f"  NET all-in     {net}  (this is the true cost of one round trip)")
        print(f"  recorded to    {ARGS.db}  (purpose=telemetry_probe)")


def main() -> None:
    if settings.ENV == "live" and CONFIRMED:
        print("*** LIVE PROBE on a real account -- real money ***")
    Probe().run()


if __name__ == "__main__":
    main()
