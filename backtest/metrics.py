"""Performance metrics on a per-bar net-return series. Pure functions, unit-tested.

Risk-adjusted return is the objective (spec §1) — so Sharpe/Sortino/Calmar and drawdown
are first-class, not total return. All computed on returns AFTER costs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Approx bars per year by cTrader period (FX trades ~24h x ~5 days).
BARS_PER_YEAR = {
    "M1": 60 * 24 * 260, "M5": 12 * 24 * 260, "M15": 4 * 24 * 260, "M30": 2 * 24 * 260,
    "H1": 24 * 260, "H4": 6 * 260, "D1": 260, "W1": 52,
}


def sharpe(returns: pd.Series, periods_per_year: float) -> float:
    r = returns.dropna()
    sd = r.std(ddof=0)
    if sd == 0 or len(r) == 0:
        return 0.0
    return float(r.mean() / sd * np.sqrt(periods_per_year))


def sortino(returns: pd.Series, periods_per_year: float) -> float:
    r = returns.dropna()
    downside = r[r < 0]
    dd = downside.std(ddof=0)
    if dd == 0 or len(r) == 0:
        return 0.0
    return float(r.mean() / dd * np.sqrt(periods_per_year))


def equity_curve(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod()


def max_drawdown(returns: pd.Series) -> float:
    """Most negative peak-to-trough on the equity curve. Returns <= 0."""
    eq = equity_curve(returns)
    if eq.empty:
        return 0.0
    return float((eq / eq.cummax() - 1.0).min())


def calmar(returns: pd.Series, periods_per_year: float) -> float:
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    ann_return = (1.0 + r).prod() ** (periods_per_year / len(r)) - 1.0
    mdd = abs(max_drawdown(r))
    return float(ann_return / mdd) if mdd > 0 else 0.0


def summarize(net_returns: pd.Series, trade_pnls: list[float], periods_per_year: float) -> dict:
    wins = [t for t in trade_pnls if t > 0]
    return {
        "sharpe": round(sharpe(net_returns, periods_per_year), 3),
        "sortino": round(sortino(net_returns, periods_per_year), 3),
        "calmar": round(calmar(net_returns, periods_per_year), 3),
        "max_drawdown": round(max_drawdown(net_returns), 4),
        "total_return": round(float((1.0 + net_returns.fillna(0.0)).prod() - 1.0), 4),
        "num_trades": len(trade_pnls),
        "win_rate": round(len(wins) / len(trade_pnls), 3) if trade_pnls else 0.0,
        "avg_trade": round(float(np.mean(trade_pnls)), 6) if trade_pnls else 0.0,
    }
