"""The hypothesis families with published evidence, as position rules. Pure functions.

Every rule returns, for each bar t, the position to HOLD during bar t (from t-1 close to t
close), computed only from closes up to t-1. So `position * bar_return` is point-in-time.
Positions are -1, 0 or +1 per instrument: at the broker's minimum size there is no room for
volatility scaling, so the test is of the sign, which is what a minimum-size trade can do.

Families (citations are the claims being re-tested, not endorsements):
  tsmom      time-series momentum. Moskowitz, Ooi and Pedersen, "Time series momentum",
             J. Financial Economics 104(2), 2012. Sign of the past L-day return.
  reversal   short-term reversal. Lehmann, "Fads, martingales and market efficiency", QJE
             105(1), 1990; Jegadeesh, J. Finance 45(3), 1990. Minus the sign of the past L-day
             return.
  turn_month turn of the month. Lakonishok and Smidt, "Are seasonal anomalies real?", Review of
             Financial Studies 1(4), 1988. Long from the last trading day of a month through
             the third trading day of the next.
  carry      FX carry. Koijen, Moskowitz, Pedersen and Vrugt, "Carry", JFE 127(2), 2018;
             Menkhoff, Sarno, Schmeling and Schrimpf, "Carry trades and global foreign exchange
             volatility", J. Finance 67(2), 2012. Long the higher-rate currency, using rates
             only after their publication lag.
  xs_mom     currency cross-sectional momentum. Menkhoff, Sarno, Schmeling and Schrimpf,
             "Currency momentum strategies", JFE 106(3), 2012. Each month rank currencies
             against the dollar by their past L-day return; long the top 3, short the bottom 3.
  time_of_day intraday FX seasonality. Breedon and Ranaldo, "Intraday patterns in FX returns
             and order flow", J. Money, Credit and Banking 45(5), 2013: a currency tends to
             fall during its own country's trading hours. On H1 bars: hold foreign-vs-USD long
             during US hours (13:00 to 21:00 UTC).

Currency VALUE (Menkhoff et al. 2017, real exchange rates) is NOT here: the engine holds no
purchasing-power-parity or real-exchange-rate data, and a proxy would be a different claim.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

#: (family, variant name, params). Every row x every instrument it applies to is one trial.
VARIANTS: list[tuple[str, str, dict]] = [
    ("tsmom", "tsmom_21", {"lookback": 21}),
    ("tsmom", "tsmom_63", {"lookback": 63}),
    ("tsmom", "tsmom_252", {"lookback": 252}),
    ("reversal", "reversal_5", {"lookback": 5}),
    ("reversal", "reversal_21", {"lookback": 21}),
    ("turn_month", "turn_month", {"before": 1, "after": 3}),
    ("carry", "carry_any", {"min_diff_pct": 0.0}),
    ("carry", "carry_1pct", {"min_diff_pct": 1.0}),
    ("time_of_day", "us_hours_long_foreign", {"start_utc": 13, "end_utc": 21}),
]
#: Portfolio variants (one trial each): the whole cross-section is one candidate.
PORTFOLIO_VARIANTS: list[tuple[str, str, dict]] = [
    ("xs_mom", "xs_mom_21", {"lookback": 21, "top": 3}),
    ("xs_mom", "xs_mom_63", {"lookback": 63, "top": 3}),
]
#: Families that are replications of published results (t bar 2.0) vs new (t bar 3.0).
PUBLISHED = {"tsmom", "reversal", "turn_month", "carry", "xs_mom", "time_of_day"}


def _sign_of_past_return(close: pd.Series, lookback: int) -> pd.Series:
    past = close / close.shift(lookback) - 1.0
    return np.sign(past).shift(1).fillna(0.0)


def tsmom(close: pd.Series, lookback: int) -> pd.Series:
    return _sign_of_past_return(close, lookback)


def reversal(close: pd.Series, lookback: int) -> pd.Series:
    return -_sign_of_past_return(close, lookback)


def turn_month(dates: pd.DatetimeIndex, before: int = 1, after: int = 3) -> pd.Series:
    """+1 on the last `before` weekdays of a month and the first `after` weekdays of the next.

    Defined on the weekday calendar, not on which bars happen to exist, so it is known in
    advance for any date (no future data, and the forward test computes it the same way).
    """
    return pd.Series([1.0 if is_turn_of_month(ts, before, after) else 0.0 for ts in dates],
                     index=dates)


@lru_cache(maxsize=1024)
def _weekdays(year: int, month: int) -> tuple[int, ...]:
    start = pd.Timestamp(year=year, month=month, day=1)
    return tuple(d.day for d in pd.bdate_range(start, start + pd.offsets.MonthEnd(0)))


def is_turn_of_month(ts, before: int = 1, after: int = 3) -> bool:
    t = pd.Timestamp(ts)
    if t.weekday() >= 5:
        return False
    days = _weekdays(t.year, t.month)
    i = days.index(t.day)
    return i < after or i >= len(days) - before


def carry(dates: pd.DatetimeIndex, differential_pct: pd.Series, min_diff_pct: float) -> pd.Series:
    """Sign of the (base minus quote) rate differential, if it is at least min_diff_pct."""
    d = differential_pct.reindex(dates).ffill()
    pos = np.where(d.abs() >= max(min_diff_pct, 1e-12), np.sign(d), 0.0)
    return pd.Series(pos, index=dates).shift(1).fillna(0.0)


def time_of_day(ts_utc: pd.DatetimeIndex, usd_is_quote: bool, start_utc: int,
                end_utc: int) -> pd.Series:
    """Hold the foreign currency against the dollar during US hours [start, end) UTC.

    For XXXUSD that is long; for USDXXX it is short. Bar t covers the hour that STARTS at its
    open; a bar's hour is known in advance, so this is point-in-time by construction.
    """
    hour = pd.Series(ts_utc.hour, index=ts_utc)
    on = (hour >= start_utc) & (hour < end_utc)
    return on.astype(float) * (1.0 if usd_is_quote else -1.0)


def xs_momentum(closes_vs_usd: pd.DataFrame, lookback: int, top: int,
                rebalance_every: int = 21) -> pd.DataFrame:
    """Weights per currency (columns: foreign currency priced in USD, higher = foreign up).

    Every `rebalance_every` bars, rank by past `lookback` return (to t-1), +1 on the top `top`,
    -1 on the bottom `top`; hold until the next rebalance.
    """
    past = (closes_vs_usd / closes_vs_usd.shift(lookback) - 1.0).shift(1)
    w = pd.DataFrame(np.nan, index=closes_vs_usd.index, columns=closes_vs_usd.columns)
    for i in range(lookback + 1, len(w), rebalance_every):
        row = past.iloc[i].dropna()
        if len(row) < 2 * top:
            continue
        order = row.sort_values()
        x = pd.Series(0.0, index=closes_vs_usd.columns)
        x[order.index[-top:]] = 1.0
        x[order.index[:top]] = -1.0
        w.iloc[i] = x
    return w.ffill().fillna(0.0)
