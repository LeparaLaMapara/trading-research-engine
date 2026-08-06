"""Pair-selection opportunity map (spec section 3.4).

A cost-vs-activity ranking of the instruments we have telemetry for. Cheapest median spread
first, with a tick count as a crude activity proxy. This is a shortlist tool: cheap AND
active is where an edge has room to survive costs.
"""
from __future__ import annotations

import sqlite3

import pandas as pd


def rank_pairs(telemetry_db: str) -> pd.DataFrame:
    """Per-symbol median spread and tick count, cheapest spread first.

    Returns a DataFrame with columns symbol, median_spread_pips, tick_count. An empty frame
    (same columns) is returned when there is no telemetry.
    """
    cols = ["symbol", "median_spread_pips", "tick_count"]
    try:
        conn = sqlite3.connect(telemetry_db)
        try:
            df = pd.read_sql_query("SELECT symbol, spread_pips FROM ticks", conn)
        finally:
            conn.close()
    except Exception:
        return pd.DataFrame(columns=cols)

    df = df.dropna(subset=["symbol"])
    if df.empty:
        return pd.DataFrame(columns=cols)

    g = df.groupby("symbol")
    out = g.agg(
        median_spread_pips=("spread_pips", "median"),
        tick_count=("spread_pips", "size"),
    ).reset_index()
    out = out.sort_values("median_spread_pips", ascending=True).reset_index(drop=True)
    return out[cols]
