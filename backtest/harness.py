"""Minimal but honest backtest harness.

Rules it enforces (spec §6):
  * Point-in-time: the position held during bar t comes from the strategy's shifted signal
    (data <= t-1). The harness never uses bar t's close to decide bar t's position.
  * Costs are charged on every position change: crossing the spread (measured from the
    owner's own telemetry) plus commission. No frictionless fills.
  * Reproducible: pure function of (bars, strategy, costs). No randomness, no I/O.

It is deliberately simple: next-bar returns, symmetric costs per unit turnover. It does
NOT yet do walk-forward refitting or multiple-testing correction — and it must not be
trusted as evidence until it does (see report caveats). Its job here is to prove the
pipeline runs end-to-end.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest import metrics
from strategy.base import Strategy


@dataclass
class CostModel:
    """Round-trip cost split into the two frictions we can measure/quote."""
    spread_pips: float          # measured median spread for this symbol/hour (from telemetry)
    pip_size: float             # 10**-pip_position (e.g. 0.0001 EURUSD, 0.01 JPY/XAU)
    ref_price: float            # representative price, to turn a price spread into a return
    commission_per_side: float = 0.000035   # ~$3.5/side per $100k notional (IC raw), as a fraction
    #: Broker overnight financing as a fraction of notional a year (data/swaps.json, the fee
    #: part). Charged for every 17:00 New York rollover a position is held through. 0 keeps the
    #: old behaviour; any rule that holds overnight must set it or its result is too kind.
    financing_annual: float = 0.0
    #: "fx": weekday rollovers, Wednesday counts three nights (the weekend). "daily": crypto
    #: CFDs, charged every night including weekends.
    rollover_style: str = "fx"

    def cost_per_unit_turnover(self) -> float:
        """Cost as a return fraction for a position change of 1.0 (one spread crossing).
        Half the spread on entry + half on exit == one full spread per round trip; per unit
        of |Δposition| that is half a spread, plus one side of commission."""
        spread_return = (self.spread_pips * self.pip_size) / self.ref_price
        return 0.5 * spread_return + self.commission_per_side


def rollover_nights(ts_utc: pd.Series, style: str = "fx") -> pd.Series:
    """Nights of financing charged during each bar: rollovers (17:00 New York) that fall inside
    (end of previous bar, end of this bar]. `ts_utc` is the bar OPEN time in seconds; the bar
    length is the median spacing. The position held during bar i is the one financed."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    ts = pd.Series(ts_utc).astype("int64").to_numpy()
    if len(ts) < 2:
        return pd.Series(np.zeros(len(ts)))
    step = int(np.median(np.diff(ts)))
    ends = ts + step
    first = pd.Timestamp(ends[0] - step, unit="s", tz="UTC").tz_convert(ny).normalize()
    last = pd.Timestamp(ends[-1], unit="s", tz="UTC").tz_convert(ny).normalize()
    days = pd.date_range(first - pd.Timedelta(days=1), last + pd.Timedelta(days=1), freq="D")
    rolls, weights = [], []
    for d in days:
        wd = d.weekday()                       # Monday 0 .. Sunday 6
        if style == "fx":
            if wd >= 5:
                continue                       # no rollover Saturday or Sunday
            w = 3 if wd == 2 else 1
        elif style == "daily":
            w = 1
        else:
            raise ValueError(f"unknown rollover_style {style!r}")
        roll = d.replace(hour=17).tz_localize(None).tz_localize(ny)
        rolls.append(int(roll.tz_convert("UTC").timestamp()))
        weights.append(w)
    rolls, weights = np.asarray(rolls), np.asarray(weights, dtype=float)
    cum = np.concatenate([[0.0], np.cumsum(weights)])
    prev_end = np.concatenate([[ends[0] - step], ends[:-1]])
    hi = np.searchsorted(rolls, ends, side="right")
    lo = np.searchsorted(rolls, prev_end, side="right")
    return pd.Series(cum[hi] - cum[lo])


@dataclass
class BacktestResult:
    net_returns: pd.Series
    gross_returns: pd.Series
    positions: pd.Series
    equity: pd.Series
    trade_pnls: list
    summary: dict


def run_backtest(bars: pd.DataFrame, strategy: Strategy, costs: CostModel,
                 periods_per_year: float) -> BacktestResult:
    bars = bars.sort_values("ts_utc").reset_index(drop=True)
    positions = strategy.generate_signals(bars).astype(float)

    # Sanity: a position for bar t must not depend on bar t's own close (no lookahead).
    # generate_signals is contractually shifted; we assert alignment length here.
    if len(positions) != len(bars):
        raise ValueError("strategy returned a signal series of the wrong length")

    bar_return = bars["close"].pct_change().fillna(0.0)
    gross = positions * bar_return

    turnover = positions.diff().abs().fillna(positions.abs())  # first bar: cost to open
    cost = turnover * costs.cost_per_unit_turnover()
    if costs.financing_annual:
        nights = rollover_nights(bars["ts_utc"], costs.rollover_style)
        cost = cost + positions.abs() * nights * (costs.financing_annual / 365.0)
    net = gross - cost

    equity = metrics.equity_curve(net)

    # Per-trade P&L: sum net returns over each contiguous holding segment (position != 0
    # and unchanged). A change in position closes the current trade.
    trade_pnls: list[float] = []
    cur = 0.0
    cur_pos = 0.0
    for i in range(len(positions)):
        p = positions.iloc[i]
        if p != cur_pos:
            if cur_pos != 0.0:
                trade_pnls.append(cur)
            cur = 0.0
            cur_pos = p
        if cur_pos != 0.0:
            cur += net.iloc[i]
    if cur_pos != 0.0:
        trade_pnls.append(cur)

    summary = metrics.summarize(net, trade_pnls, periods_per_year)
    return BacktestResult(net, gross, positions, equity, trade_pnls, summary)
