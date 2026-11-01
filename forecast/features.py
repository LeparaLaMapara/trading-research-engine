"""Inputs for the E16 model, from hourly bars only (docs/programme/E16-forward-scoreboard-prereg.md).

A row is one instrument at one hour: the bar that OPENED at `ts` (UTC seconds) and closed an
hour later. Everything in the row is known at that close. The target is the next bar's return
divided by the 24-hour volatility known now.
"""
from __future__ import annotations

import json
import os
import sqlite3

import numpy as np
import pandas as pd

MARKET_DB = "data/market.db"
NY = "America/New_York"
FEATURES = ["ret1", "ret4", "ret24", "ret120", "vol24", "vol120", "ma24", "ma120",
            "hour_ny", "weekday", "nfp", "cpi", "fomc", "asset", "xs_ret1", "xs_ret24"]
CRYPTO = {"BTCUSD", "ETHUSD", "LTCUSD", "BCHUSD", "ADAUSD", "SOLUSD", "XRPUSD", "DOTUSD", "DOGUSD"}
METALS = {"XAUUSD", "XAGUSD", "XAUEUR", "XPDUSD", "XPTUSD"}
ENERGY = {"XTIUSD", "XBRUSD", "XNGUSD"}


def asset_class(sym: str) -> int:
    if sym in CRYPTO:
        return 4
    if sym in METALS:
        return 2
    if sym in ENERGY:
        return 3
    if len(sym) == 6 and sym.isalpha():
        return 0                                  # currency pair
    return 1                                      # stock index


def load_bars(db: str = MARKET_DB, symbols: list[str] | None = None, since: float = 0) -> pd.DataFrame:
    q = "select symbol, ts_utc as ts, close from bars where period='H1' and ts_utc >= ?"
    with sqlite3.connect(db) as c:
        df = pd.read_sql(q, c, params=(since,))
    if symbols is not None:
        df = df[df.symbol.isin(symbols)]
    df["ts"] = df["ts"].astype("int64")
    return df.drop_duplicates(["symbol", "ts"]).sort_values(["symbol", "ts"]).reset_index(drop=True)


def event_dates() -> dict[str, set]:
    out = {"nfp": set(), "cpi": set(), "fomc": set()}
    if os.path.exists("data/releases.json"):
        with open("data/releases.json", encoding="utf-8") as fh:
            rel = json.load(fh)
        out["nfp"] = {r["date"] for r in rel.get("NFP", [])}
        out["cpi"] = {r["date"] for r in rel.get("CPI", [])}
    if os.path.exists("data/fomc_dates.json"):
        from news import fomc
        out["fomc"] = {str(pd.Timestamp(d).date()) for d in fomc.load()}
    return out


def _per_symbol(g: pd.DataFrame) -> pd.DataFrame:
    lc = np.log(g["close"].to_numpy(float))
    s = pd.Series(lc, index=g.index)
    r1 = s.diff()
    vol24 = r1.rolling(24, min_periods=20).std()
    vol120 = r1.rolling(120, min_periods=100).std()
    out = pd.DataFrame(index=g.index)
    for k in (1, 4, 24, 120):
        out[f"ret{k}"] = (s - s.shift(k)) / (vol24 * np.sqrt(k))
    out["vol24"] = vol24
    out["vol120"] = vol120
    out["ma24"] = (s - s.rolling(24).mean()) / vol24
    out["ma120"] = (s - s.rolling(120).mean()) / vol24
    nxt_ok = (g["ts"].shift(-1) - g["ts"]) == 3600
    out["target"] = np.where(nxt_ok, r1.shift(-1) / vol24, np.nan)
    return out


def make_features(bars: pd.DataFrame, events: dict | None = None) -> pd.DataFrame:
    """One row per (symbol, ts) with FEATURES and `target` (NaN where the next hour is missing)."""
    events = events if events is not None else event_dates()
    parts = [_per_symbol(g) for _, g in bars.groupby("symbol", sort=False)]
    f = pd.concat(parts).loc[bars.index]
    df = pd.concat([bars[["symbol", "ts", "close"]], f], axis=1)
    close_ny = pd.to_datetime(df["ts"] + 3600, unit="s", utc=True).dt.tz_convert(NY)
    df["hour_ny"] = close_ny.dt.hour
    df["weekday"] = close_ny.dt.weekday
    day = close_ny.dt.strftime("%Y-%m-%d")
    for k in ("nfp", "cpi", "fomc"):
        df[k] = day.isin(events[k]).astype(int)
    df["asset"] = df["symbol"].map(asset_class)
    for k in ("ret1", "ret24"):
        df[f"xs_{k}"] = df.groupby("ts")[k].rank(pct=True)
    df = df.replace([np.inf, -np.inf], np.nan)
    return df
