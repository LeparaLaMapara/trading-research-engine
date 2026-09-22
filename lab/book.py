"""Rebuild an order book from the broker's depth events and sample it once a second (E03).

The depth feed sends quotes (id, side, price, size) and deletions by id. The book at any moment
is every quote added and not yet deleted. Pure functions, so the reconstruction can be tested
on synthetic events before it touches evaluation data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LEVELS = 5


def per_second(events: pd.DataFrame, levels: int = LEVELS) -> pd.DataFrame:
    """One row per whole second: best bid, best ask, top-`levels` sizes and the imbalance.

    `events` has ts_utc, quote_id, side ('bid' | 'ask' | 'delete'), price, size, event
    ('new' | 'deleted'), in arrival order. A second's row is the book after the LAST event at
    or before the end of that second. Seconds with no bid or no ask are dropped.
    """
    book: dict[int, tuple[str, float, float]] = {}
    out = []
    ev = events.sort_values(["ts_utc"], kind="stable")
    for ts, g in ev.groupby("ts_utc", sort=True):
        for qid, side, price, size, kind in zip(g["quote_id"], g["side"], g["price"],
                                                g["size"], g["event"]):
            if kind == "new":
                book[qid] = (side, price, size)
            else:
                book.pop(qid, None)
        bids = sorted(((p, s) for sd, p, s in book.values() if sd == "bid"), reverse=True)
        asks = sorted((p, s) for sd, p, s in book.values() if sd == "ask")
        if not bids or not asks:
            continue
        b = sum(s for _, s in bids[:levels])
        a = sum(s for _, s in asks[:levels])
        out.append((ts, bids[0][0], asks[0][0], b, a))
    if not out:
        return pd.DataFrame(columns=["bid", "ask", "B", "A", "I", "mid"])
    df = pd.DataFrame(out, columns=["ts", "bid", "ask", "B", "A"])
    df["sec"] = np.floor(df["ts"]).astype("int64")
    df = df.groupby("sec").last().drop(columns="ts")
    # Carry the last known book forward through quiet seconds, but not across a gap longer
    # than 5 seconds: a book that stopped updating is a recording gap, not a quiet market.
    full = pd.RangeIndex(df.index.min(), df.index.max() + 1)
    df = df.reindex(full).ffill(limit=5).dropna()
    tot = df["B"] + df["A"]
    df["I"] = np.where(tot > 0, (df["B"] - df["A"]) / tot.replace(0, np.nan), 0.0)
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df = df[df["ask"] > df["bid"]]
    return df


def future(df: pd.DataFrame, col: str, offset: int) -> pd.Series:
    """Value of `col` exactly `offset` seconds later, NaN if that second is missing."""
    return df[col].reindex(df.index + offset).set_axis(df.index)


def trades(df: pd.DataFrame, threshold: float = 0.6, delay: int = 2, hold: int = 60,
           commission_side: float = 0.000035) -> pd.DataFrame:
    """The pre-registered rule: signal at t, enter at t+delay crossing the book, exit at
    t+delay+hold crossing it, one trade at a time."""
    ask_in, bid_in = future(df, "ask", delay), future(df, "bid", delay)
    ask_out, bid_out = future(df, "ask", delay + hold), future(df, "bid", delay + hold)
    rows, busy_until = [], None
    for t, i in df["I"].items():
        if busy_until is not None and t <= busy_until:
            continue
        if abs(i) < threshold:
            continue
        side = 1 if i > 0 else -1
        entry = ask_in[t] if side == 1 else bid_in[t]
        exit_ = bid_out[t] if side == 1 else ask_out[t]
        if not (np.isfinite(entry) and np.isfinite(exit_)) or entry <= 0:
            continue
        net = side * (exit_ - entry) / entry - 2 * commission_side
        rows.append((t, side, i, entry, exit_, net))
        busy_until = t + delay + hold
    return pd.DataFrame(rows, columns=["t", "side", "I", "entry", "exit", "net"])
