"""Forecast -> position -> portfolio P&L, identical for every model in the zoo.

Units. A forecast f is dimensionless (mean |f| = 1 on training data, capped at +/-2). The
position in NOTIONAL (fraction of capital, before a common leverage scale) is f / sigma, so
each unit of forecast carries the same daily risk on every instrument. Per instrument P&L is
notional * next return, costs are |change in notional| * cost per unit notional traded, and
financing is |notional| * annual rate / bars per year. The portfolio is the sum across
instruments divided by the number alive on that date. A common leverage factor does not change Sharpe.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from backtest.run import measured_cost

CAP = 2.0
BUFFER = 0.25

#: Financing on held notional, charged in BOTH directions. Conservative: ignores carry earned.
FINANCING = {"fx_major": 0.010, "fx_cross": 0.010, "index": 0.030, "metal": 0.025,
             "energy": 0.030, "crypto": 0.15}
#: Crypto trades every day; everything else about 260 bars a year.
BARS_PER_YEAR = {"crypto": 365.0}

#: Pessimistic spread overrides (bps of price, round trip) for extended instruments with no
#: telemetry, where the class default is too kind. Assumptions, stated, not measurements.
SPREAD_OVERRIDE_BPS = {
    "USDZAR": 10, "EURZAR": 15, "USDMXN": 10, "USDNOK": 8, "USDSEK": 8, "EURNOK": 8,
    "EURSEK": 8, "USDSGD": 6, "USDPLN": 10, "XPTUSD": 15, "XPDUSD": 25, "XNGUSD": 12,
    "CHINA50": 5, "SA40": 8, "CA60": 5, "ES35": 4, "IT40": 4, "US2000": 4, "JP225": 3,
    "SOLUSD": 20, "XRPUSD": 20, "LTCUSD": 25, "BCHUSD": 25, "DOTUSD": 30,
}


#: "measured" = broker swap fee per symbol (zoo.financing, data/swaps.json, captured
#: 2026-09-19), falling back to the class median of measured fees; "assumed" = FINANCING above,
#: the pre-registered values. Measured became the default the day it existed; results under
#: "assumed" are kept for comparison.
FINANCING_MODE = os.environ.get("ZOO_FINANCING", "measured")


def _measured_fees(panel: pd.DataFrame) -> dict[str, float]:
    from zoo.financing import fee_and_differential, load
    try:
        sw = load()
    except OSError:
        return {}
    last = panel.sort_values("date").groupby("symbol")["close"].last()
    return {s: max(fee_and_differential(sw[s], float(last[s]))[0], 0.0)
            for s in last.index if s in sw}


def cost_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Per instrument: cost per unit notional traded, and financing per bar."""
    fees = _measured_fees(panel) if FINANCING_MODE == "measured" else {}
    cls_of = panel.groupby("symbol")["asset_class"].first()
    cls_med = pd.Series(fees).groupby(cls_of.reindex(list(fees)).to_numpy()).median().to_dict()         if fees else {}
    rows = []
    for sym, g in panel.groupby("symbol"):
        cls = g["asset_class"].iloc[0]
        if sym in SPREAD_OVERRIDE_BPS:
            c = 0.5 * SPREAD_OVERRIDE_BPS[sym] * 1e-4 + 0.000035
            src = "override"
        else:
            cm = measured_cost(sym, ref_price=float(g["close"].mean()))
            c = cm.cost_per_unit_turnover()
            src = "model"
        annual = fees.get(sym, cls_med.get(cls, FINANCING.get(cls, 0.03))) if fees             else FINANCING.get(cls, 0.03)
        fin = annual / BARS_PER_YEAR.get(cls, 260.0)
        rows.append({"symbol": sym, "cost": c, "fin": fin, "cost_src": src})
    return pd.DataFrame(rows).set_index("symbol")


def buffered(f: np.ndarray) -> np.ndarray:
    """Hold the previous position unless the new target moves by more than BUFFER."""
    out = np.empty_like(f)
    held = 0.0
    for i, x in enumerate(f):
        if np.isnan(x):
            x = 0.0
        if abs(x - held) > BUFFER:
            held = x
        out[i] = held
    return out


def portfolio_returns(panel: pd.DataFrame, forecast: pd.Series, costs: pd.DataFrame,
                      mask: pd.Series | None = None,
                      income: pd.Series | None = None) -> pd.DataFrame:
    """Daily portfolio gross and net returns for rows selected by `mask`.

    The buffer and cost are computed over each instrument's WHOLE forecast path in date order,
    then restricted to the window, so the first day of a window is not charged a full entry
    that a continuous strategy would never have paid.
    """
    df = panel[["date", "symbol", "sigma", "fwd_ret"]].copy()
    df["f"] = forecast.clip(-CAP, CAP).to_numpy()
    # Per-bar income earned by a LONG unit of notional (e.g. an FX interest differential);
    # a short earns its negative. Zero when not supplied.
    df["inc"] = 0.0 if income is None else income.fillna(0.0).to_numpy()
    df = df.join(costs, on="symbol")
    df = df.sort_values(["symbol", "date"])
    df["pos"] = df.groupby("symbol")["f"].transform(lambda s: pd.Series(buffered(s.to_numpy()),
                                                                         index=s.index))
    df["notional"] = df["pos"] / df["sigma"]
    prev = df.groupby("symbol")["notional"].shift(1).fillna(0.0)
    df["gross"] = df["notional"] * (df["fwd_ret"] + df["inc"])
    df["tcost"] = (df["notional"] - prev).abs() * df["cost"]
    df["fcost"] = df["notional"].abs() * df["fin"]
    df["net"] = df["gross"] - df["tcost"] - df["fcost"]
    df["turn"] = (df["pos"] - df.groupby("symbol")["pos"].shift(1).fillna(0.0)).abs()
    df = df.dropna(subset=["fwd_ret"])
    if mask is not None:
        df = df[mask.reindex(df.index).fillna(False).to_numpy()]
    # Divide by instruments ALIVE on the date (listed and not yet ended), not by those that
    # happened to trade. Otherwise a weekend, when only crypto trades, would put the whole
    # book into crypto for a day.
    life = panel.groupby("symbol")["date"].agg(["min", "max"])
    daily = df.groupby("date").agg(gross=("gross", "sum"), net=("net", "sum"),
                                   tcost=("tcost", "sum"), fcost=("fcost", "sum"),
                                   turn=("turn", "sum"), n=("symbol", "count"))
    d = daily.index.to_numpy()
    alive = ((life["min"].to_numpy()[None, :] <= d[:, None])
             & (life["max"].to_numpy()[None, :] >= d[:, None])).sum(axis=1)
    cols = ["gross", "net", "tcost", "fcost", "turn"]
    daily[cols] = daily[cols].div(np.maximum(alive, 1), axis=0)
    daily["alive"] = alive
    return daily


def per_instrument_net(panel: pd.DataFrame, forecast: pd.Series, costs: pd.DataFrame,
                       mask: pd.Series) -> pd.Series:
    """Net annualised Sharpe per instrument over the masked window (for diagnostics)."""
    df = panel[["date", "symbol", "sigma", "fwd_ret"]].copy()
    df["f"] = forecast.clip(-CAP, CAP).to_numpy()
    df = df.join(costs, on="symbol").sort_values(["symbol", "date"])
    df["pos"] = df.groupby("symbol")["f"].transform(lambda s: pd.Series(buffered(s.to_numpy()),
                                                                         index=s.index))
    df["notional"] = df["pos"] / df["sigma"]
    prev = df.groupby("symbol")["notional"].shift(1).fillna(0.0)
    df["net"] = (df["notional"] * df["fwd_ret"] - (df["notional"] - prev).abs() * df["cost"]
                 - df["notional"].abs() * df["fin"])
    df = df.dropna(subset=["fwd_ret"])
    df = df[mask.reindex(df.index).fillna(False).to_numpy()]
    return df.groupby("symbol")["net"].apply(
        lambda x: x.mean() / x.std() * np.sqrt(260) if x.std() > 0 else 0.0)
