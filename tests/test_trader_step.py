"""The live trader's limits and close decisions (pure parts of scripts/trader_step.py)."""
from __future__ import annotations

from scripts.trader_step import RESIZE_AT, limits_check, should_close

LONG = {"side": 1, "id": 1, "volume": 1}


def test_signal_change_closes():
    assert should_close(LONG, -1, 100.0, 100.0) == "signal changed"
    assert should_close(LONG, 0, 100.0, 100.0) == "signal changed"


def test_same_signal_keeps_until_equity_grows_by_half():
    assert should_close(LONG, 1, 100.0, 100.0) is None
    assert should_close(LONG, 1, RESIZE_AT * 100.0 - 0.01, 100.0) is None
    assert should_close(LONG, 1, RESIZE_AT * 100.0, 100.0).startswith("resize")


def test_nothing_to_close_when_flat():
    assert should_close(None, 1, 100.0, None) is None


def test_floor_and_drawdown_halt_on_equity():
    st = {}
    assert limits_check(st, 100.0, "d1")[0] is None
    assert "drawdown" in limits_check(st, 59.0, "d2")[0]          # 41% below the 100 peak
    assert "floor" in limits_check({}, 19.0, "d1")[0]


def test_daily_loss_blocks_new_trades_but_does_not_halt():
    st = {}
    limits_check(st, 100.0, "d1")
    halt, blocked, pnl = limits_check(st, 89.0, "d1")
    assert halt is None and blocked and pnl == -11.0
    halt, blocked, _ = limits_check(st, 89.0, "d2")               # a new day starts afresh
    assert halt is None and not blocked
