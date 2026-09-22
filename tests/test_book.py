"""E03's book reconstruction and trade rule, on synthetic depth events."""
from __future__ import annotations

import pandas as pd

from lab import book as B


def _ev(rows):
    return pd.DataFrame(rows, columns=["ts_utc", "quote_id", "side", "price", "size", "event"])


def test_book_adds_and_deletes_quotes():
    ev = _ev([(0.1, 1, "bid", 99.0, 30, "new"), (0.1, 2, "ask", 101.0, 10, "new"),
              (1.2, 1, "delete", None, None, "deleted"), (1.2, 3, "bid", 99.5, 10, "new")])
    df = B.per_second(ev)
    assert df.loc[0, "bid"] == 99.0 and df.loc[0, "I"] == (30 - 10) / 40
    assert df.loc[1, "bid"] == 99.5 and df.loc[1, "I"] == 0.0


def test_only_top_levels_count():
    rows = [(0.0, i, "bid", 100 - i, 1, "new") for i in range(1, 8)]
    rows += [(0.0, 100, "ask", 101, 5, "new")]
    df = B.per_second(_ev(rows), levels=5)
    assert df.loc[0, "B"] == 5 and df.loc[0, "A"] == 5


def test_quiet_seconds_carry_forward_but_long_gaps_do_not():
    ev = _ev([(0.0, 1, "bid", 99, 1, "new"), (0.0, 2, "ask", 101, 1, "new"),
              (20.0, 3, "bid", 99, 1, "new")])
    df = B.per_second(ev)
    assert 5 in df.index and 6 not in df.index


def _flat_book(n=200, imbalance_at=(10,), price_path=None):
    """A per-second frame built directly: spread 0.02, imbalance 0.8 at chosen seconds."""
    idx = pd.RangeIndex(0, n)
    mid = pd.Series(price_path if price_path is not None else [1.0] * n, index=idx, dtype=float)
    df = pd.DataFrame({"bid": mid - 0.01, "ask": mid + 0.01}, index=idx)
    df["I"] = 0.0
    for t in imbalance_at:
        df.loc[t, "I"] = 0.8
    return df


def test_rule_enters_after_the_delay_and_crosses_the_book():
    path = [1.0] * 12 + [1.5] * 188          # jumps at t=12, after entry at t=10+2
    tr = B.trades(_flat_book(price_path=path), delay=2, hold=60, commission_side=0.0)
    assert len(tr) == 1
    t = tr.iloc[0]
    assert t["side"] == 1 and t["entry"] == 1.51 and t["exit"] == 1.49


def test_no_new_trade_while_one_is_open():
    tr = B.trades(_flat_book(imbalance_at=(10, 20, 80)), delay=2, hold=60)
    assert list(tr["t"]) == [10, 80]


def test_costs_make_a_flat_market_lose():
    tr = B.trades(_flat_book(), commission_side=0.000035)
    assert (tr["net"] < 0).all()
