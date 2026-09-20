"""Separate PREDICTION from EXECUTION, then name the failure.

A single net number cannot tell you whether a strategy is stupid or merely expensive, and those
two findings lead to completely different next experiments. So every candidate is broken into:

    theoretical signal value        gross, before any friction
  - spread and commission          measured, per instrument
  - financing                      measured from the broker's own swap quotes
  - latency cost                   from the edge-decay replay, where data can price it
  - slippage                       NOT separately measured yet, and said so
  = realised edge

and then classified with a closed vocabulary, so "it did not work" is never the whole answer.

All components are expressed in ANNUALISED SHARPE UNITS against the same gross volatility, so
they add up and can be compared across instruments with different price scales.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: Closed vocabulary. The first six come from the brief; the last two are ours, because
#: "not enough data" and "enough data, effect too small to distinguish from luck" demand
#: different next steps and collapsing them would hide which one we are in.
VERDICTS = ("NO_PREDICTIVE_EDGE", "EDGE_DESTROYED_BY_COSTS", "EDGE_DESTROYED_BY_LATENCY",
            "EDGE_DESTROYED_BY_SLIPPAGE", "UNSTABLE_ACROSS_REGIMES", "INSUFFICIENT_DATA",
            "NOT_DISTINGUISHABLE_FROM_LUCK", "POTENTIALLY_VALID")

MIN_TRADES = 30
MIN_OBS = 250
MIN_YEARS_POSITIVE = 0.5      # fraction of years that must be positive to call it stable
DSR_BAR = 0.95


def components(daily: pd.DataFrame, af: float, latency_cost_sharpe: float | None = None) -> dict:
    """Break one candidate's daily P&L into Sharpe-unit components that sum to the net.

    `daily` has columns gross, tcost, fcost, net, as produced by zoo.portfolio.
    """
    vol = daily["gross"].std()
    if vol <= 0:
        return {"gross_sharpe": 0.0, "spread_and_fees": 0.0, "financing": 0.0,
                "latency_cost": 0.0, "net_sharpe": 0.0, "slippage": None}
    scale = np.sqrt(af) / vol
    gross = float(daily["gross"].mean() * scale)
    spread = float(daily["tcost"].mean() * scale)
    fin = float(daily["fcost"].mean() * scale)
    net_measured = float(daily["net"].mean() / daily["net"].std() * np.sqrt(af)) \
        if daily["net"].std() > 0 else 0.0
    return {
        "gross_sharpe": gross,
        "spread_and_fees": spread,
        "financing": fin,
        # None means NOT MEASURED, which is different from zero and must never print as zero.
        "latency_cost": latency_cost_sharpe,
        "slippage": None,
        "net_sharpe": net_measured,
        "residual_check": gross - spread - fin,
    }


def classify(comp: dict, n_trades: int, n_obs: int, years_positive: int, years_total: int,
             dsr: float | None, turnover_per_year: float | None = None) -> tuple[str, str]:
    """(verdict, one-line reason). Order matters: the first true statement wins.

    The trade-count test applies only to things that TRADE. A buy-and-hold makes one trade in
    eight years and is not thereby unjudgeable: it has 1,900 daily observations. Judging it on
    trade count filed the most informative baseline in the sweep under INSUFFICIENT_DATA.
    """
    if n_obs < MIN_OBS:
        return ("INSUFFICIENT_DATA", f"only {n_obs} observations")
    trades_enough = n_trades >= MIN_TRADES
    barely_trades = turnover_per_year is not None and turnover_per_year < 1.0
    if not trades_enough and not barely_trades:
        return ("INSUFFICIENT_DATA",
                f"{n_trades} trades over {n_obs} observations is too little to judge")

    gross = comp["gross_sharpe"]
    costs = comp["spread_and_fees"] + comp["financing"]
    lat = comp["latency_cost"]
    net = comp["net_sharpe"]

    if gross <= 0:
        return ("NO_PREDICTIVE_EDGE",
                f"gross Sharpe {gross:.2f} before any friction: the signal itself is worthless")

    if net <= 0:
        if lat is not None and lat > 0 and (gross - costs) > 0:
            return ("EDGE_DESTROYED_BY_LATENCY",
                    f"gross {gross:.2f} survives costs ({costs:.2f}) but not the "
                    f"{lat:.2f} lost to execution delay")
        return ("EDGE_DESTROYED_BY_COSTS",
                f"gross {gross:.2f} against {costs:.2f} of spread, fees and financing")

    if years_total and years_positive / years_total < MIN_YEARS_POSITIVE:
        return ("UNSTABLE_ACROSS_REGIMES",
                f"net is positive overall but in only {years_positive} of {years_total} years")

    if dsr is not None and dsr >= DSR_BAR:
        return ("POTENTIALLY_VALID",
                f"net {net:.2f}, deflated Sharpe {dsr:.2f} clears the {DSR_BAR} bar")

    return ("NOT_DISTINGUISHABLE_FROM_LUCK",
            f"net {net:.2f} is positive but deflated Sharpe "
            f"{'unknown' if dsr is None else f'{dsr:.2f}'} does not clear {DSR_BAR}")


def latency_cost_from_curve(curve: pd.DataFrame, operating_delay_s: float) -> float | None:
    """Sharpe lost between zero delay and the finest bucket the DATA can price.

    Returns None when no bucket at or below the operating delay is priceable, because an
    unmeasured cost must not be reported as zero. For a one-second operating latency against
    hourly data this is almost always None, and that is the honest answer: our latency cost is
    bounded above by the one-hour bucket, not measured at one second.
    """
    ok = curve[(curve["skipped"] == "") & curve["sharpe"].notna()]
    if ok.empty:
        return None
    zero = ok[ok["effective_delay_s"] == 0]
    at_or_below = ok[ok["effective_delay_s"] <= operating_delay_s]
    if zero.empty or at_or_below.empty:
        return None
    best_bucket = at_or_below.sort_values("effective_delay_s").iloc[-1]
    return float(zero.iloc[0]["sharpe"] - best_bucket["sharpe"])


def bound_latency_cost(curve: pd.DataFrame) -> tuple[float | None, float | None]:
    """(cost at the finest priceable delay, that delay) as an UPPER BOUND on latency cost.

    Used when the operating latency is finer than the data. Saying "at worst this much, and
    only if we were an hour late" is honest; saying "zero" is not.
    """
    ok = curve[(curve["skipped"] == "") & curve["sharpe"].notna()].sort_values("effective_delay_s")
    nonzero = ok[ok["effective_delay_s"] > 0]
    if ok.empty or nonzero.empty:
        return None, None
    zero = ok[ok["effective_delay_s"] == 0]
    if zero.empty:
        return None, None
    first = nonzero.iloc[0]
    return float(zero.iloc[0]["sharpe"] - first["sharpe"]), float(first["effective_delay_s"])
