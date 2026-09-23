"""The hourly live-state publisher: equity and broker-sourced closes.

Found 2026-09-22: equity was published as the balance (an open ETHUSD position up ~$0.98
showed equity $30.00), and closes were read only from a local trade log that CI never has.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

from scripts.push_live_state import closing_deal_rows, equity_of


def test_equity_adds_unrealised_swap_and_commission():
    rows = [{"unrealised_usd": 0.98, "swap_usd": -0.02, "commission_usd": 0.0}]
    assert equity_of(30.0, rows) == 30.96


def test_equity_is_unknown_rather_than_wrong_when_a_quote_is_missing():
    assert equity_of(30.0, [{"unrealised_usd": None}]) is None


def test_equity_with_no_positions_is_the_balance():
    assert equity_of(30.0, []) == 30.0


def _deal(pid, close=None, **kw):
    d = NS(dealId=kw.get("dealId", 1), positionId=pid, symbolId=7, tradeSide=2,
           executionTimestamp=1_758_000_000_000, executionPrice=2866.31,
           filledVolume=100, volume=100, moneyDigits=2, closePositionDetail=close)
    d.HasField = lambda name: getattr(d, name) is not None
    return d


def test_only_closing_deals_on_tracked_positions_become_trades():
    close = NS(grossProfit=238, swap=-5, commission=0, pnlConversionFee=0, moneyDigits=2)
    deals = [_deal(342510590, close, dealId=9),      # the tracked position closing
             _deal(342510590, None, dealId=8),       # its opening deal: not a close
             _deal(111, close, dealId=7)]            # an untracked probe: local log owns it
    rows = closing_deal_rows(deals, {"342510590": "live_research_trade"},
                             {7: "ETHUSD"}, {"ETHUSD": 10000})
    assert [r["trade_id"] for r in rows] == ["deal-9"]
    r = rows[0]
    assert r["net_usd"] == 2.33 and r["side"] == "SELL" and r["status"] == "CLOSED"
    assert r["volume_lots"] == 0.01 and r["purpose"] == "live_research_trade"


def test_net_deposits_counts_only_owner_money():
    from scripts.push_live_state import net_deposits
    rows = {"1": {"type": "BALANCE_DEPOSIT", "delta": 10.0},
            "2": {"type": "BALANCE_DEPOSIT", "delta": 20.0},
            "3": {"type": "BALANCE_WITHDRAW", "delta": 5.0},
            "4": {"type": "BALANCE_DEPOSIT_REBATE", "delta": 0.3}}
    assert net_deposits(rows) == 25.0
