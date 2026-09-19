"""The cross-instrument daily panel: one row per (date, instrument), features known at the
close of that date, targets from the days after it.

Every feature uses data up to and including date t only. Targets use t+1 onward and are the
ONLY forward-looking columns; they are prefixed `y_` / `fwd_` so a leak is visible by name.

Nothing is forward-filled across a closed market. An instrument with no bar on a date simply
has no row, so a portfolio can never be credited with a return nobody could have traded.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from config.instruments import asset_class_of

MARKET_DB = "data/market.db"
WARMUP = 300
VOL_SPAN = 36
MOM_H = (1, 5, 20, 60, 120, 250)
EWMAC = ((8, 32), (16, 64), (32, 128), (64, 256))
BREAKOUT = (20, 40, 80, 160)
CLASSES = ("fx_major", "fx_cross", "metal", "index", "energy", "crypto")

FEATURES = (
    [f"mom_{h}" for h in MOM_H]
    + [f"ewmac_{f}_{s}" for f, s in EWMAC]
    + [f"brk_{n}" for n in BREAKOUT]
    + ["volratio", "skew60", "dd250", "xs_rank120", "class_mom20", "risk_mom60", "class_id"]
)


def _daily(symbol: str, db: str) -> pd.DataFrame:
    c = sqlite3.connect(db)
    try:
        df = pd.read_sql_query("SELECT ts_utc, high, low, close FROM bars WHERE symbol=? "
                               "AND period='D1' ORDER BY ts_utc", c, params=(symbol,))
    finally:
        c.close()
    if df.empty:
        return df
    # Broker rolls the day at 21:00 UTC; +3h maps each bar onto the date it mostly covers.
    df["date"] = pd.to_datetime(df["ts_utc"] + 3 * 3600, unit="s").dt.normalize()
    return df.drop_duplicates("date", keep="last").set_index("date")[["high", "low", "close"]]


def _instrument_frame(symbol: str, bars: pd.DataFrame) -> pd.DataFrame:
    close = bars["close"].astype(float)
    r = close.pct_change()
    sigma = r.ewm(span=VOL_SPAN, min_periods=30).std()
    out = pd.DataFrame(index=bars.index)
    out["symbol"] = symbol
    out["asset_class"] = asset_class_of(symbol)
    out["close"] = close
    out["ret"] = r
    out["sigma"] = sigma
    for h in MOM_H:
        out[f"mom_{h}"] = (close / close.shift(h) - 1.0) / (sigma * np.sqrt(h))
    for f, s in EWMAC:
        out[f"ewmac_{f}_{s}"] = (close.ewm(span=f).mean() - close.ewm(span=s).mean()) / (close * sigma)
    for n in BREAKOUT:
        hi, lo = bars["high"].rolling(n).max(), bars["low"].rolling(n).min()
        out[f"brk_{n}"] = (close - (hi + lo) / 2.0) / (hi - lo).replace(0, np.nan)
    out["volratio"] = sigma / r.rolling(250).std()
    out["skew60"] = r.rolling(60).skew()
    out["dd250"] = (close / close.rolling(250).max() - 1.0) / (sigma * np.sqrt(250))
    # Targets. fwd_ret is the realised next-bar return used for P&L (never clipped).
    out["fwd_ret"] = r.shift(-1)
    fwd5 = sum(r.shift(-k) for k in range(1, 6))
    out["y_5"] = (fwd5 / (sigma * np.sqrt(5))).clip(-6, 6)
    out = out.iloc[WARMUP:]
    return out


def build_panel(symbols: list[str], db: str = MARKET_DB) -> pd.DataFrame:
    frames = []
    for s in symbols:
        b = _daily(s, db)
        if len(b) > WARMUP + 250:
            frames.append(_instrument_frame(s, b))
    panel = pd.concat(frames).reset_index().rename(columns={"index": "date"})
    panel = panel.dropna(subset=["sigma"]).query("sigma > 0")

    # Cross-sectional: centred rank of 120-day momentum within the asset class on each date.
    g = panel.groupby(["date", "asset_class"])["mom_120"]
    n = g.transform("count")
    rk = g.rank(pct=True)
    panel["xs_rank120"] = np.where(n >= 3, (rk - 0.5) * 2.0, np.nan)
    panel["class_mom20"] = panel.groupby(["date", "asset_class"])["mom_20"].transform("mean")

    # Risk appetite context: US500's 60-day momentum on that date (NaN when it did not trade).
    risk = panel.loc[panel["symbol"] == "US500", ["date", "mom_60"]].rename(
        columns={"mom_60": "risk_mom60"})
    panel = panel.merge(risk, on="date", how="left")
    panel["class_id"] = panel["asset_class"].map({c: i for i, c in enumerate(CLASSES)})
    return panel.sort_values(["date", "symbol"]).reset_index(drop=True)
