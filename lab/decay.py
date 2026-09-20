"""The edge-decay curve: expected net edge as a function of execution delay.

Output per delay bucket, then the two numbers the brief asks for:

  * Latency Survival Threshold: the largest delay at which expected net edge is still above
    zero, taken as the LAST bucket before the curve crosses and stays below.
  * A conservative operating target, deliberately well inside it. If an edge dies at four
    seconds you do not build for 3.9 seconds; SAFETY_FACTOR sets how far inside to sit.

Speed regimes are assigned from the measured threshold, never from what a strategy is called.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import metrics
from lab.replay import ResolutionError, fills_for_delay, pnl_from_fills, trade_segments

#: Operate at a fraction of the measured survival threshold, not at its edge.
SAFETY_FACTOR = 0.25

#: Measured from this machine: ProtoOAVersionReq round trip, 1,964 samples (telemetry.db).
#: Any strategy whose threshold sits below this cannot be run from here, whatever the maths says.
MEASURED_ORDER_PATH_MS = {"min": 369.0, "mean": 939.0, "max": 4941.0}

REGIMES = [
    (0.001, "ultra_low_latency"), (0.1, "sub_100ms"), (1.0, "sub_second"),
    (60.0, "seconds"), (3600.0, "minutes"), (14400.0, "hourly"),
    (86400.0, "multi_hour"), (float("inf"), "daily_or_slower"),
]


def regime_for(threshold_s: float | None) -> str:
    if threshold_s is None:
        return "no_edge_at_any_latency"
    for limit, name in REGIMES:
        if threshold_s <= limit:
            return name
    return "daily_or_slower"


def bucket_metrics(pnl: pd.DataFrame, bars_per_year: float) -> dict:
    net, gross = pnl["net"], pnl["gross"]
    trades = trade_segments(pnl)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    return {
        "gross_return": float(gross.sum()),
        "net_return": float(net.sum()),
        "ev_per_trade": float(np.mean(trades)) if trades else 0.0,
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "sharpe": metrics.sharpe(net, bars_per_year),
        "max_dd": metrics.max_drawdown(net),
        "spread_and_fees": float(pnl["cost"].sum()),
        "financing": float(pnl["financing"].sum()),
        "n_trades": len(trades),
        "n_obs": int(len(pnl)),
    }


def decay_curve(signals: pd.DataFrame, exec_bars: pd.DataFrame, delays_s: list[float],
                cost_per_turnover: float, financing_per_day: float = 0.0,
                exec_period: str = "H1", bars_per_year: float = 260.0) -> pd.DataFrame:
    """One row per delay bucket. Buckets finer than the data are SKIPPED, not faked."""
    rows = []
    for d in delays_s:
        try:
            fills = fills_for_delay(signals, exec_bars, d, exec_period)
        except ResolutionError as exc:
            rows.append({"requested_delay_s": d, "effective_delay_s": np.nan,
                         "skipped": str(exc), "net_return": np.nan, "sharpe": np.nan})
            continue
        if len(fills) < 30:
            rows.append({"requested_delay_s": d, "effective_delay_s": np.nan,
                         "skipped": f"only {len(fills)} fills", "net_return": np.nan,
                         "sharpe": np.nan})
            continue
        pnl = pnl_from_fills(fills, cost_per_turnover, financing_per_day)
        m = bucket_metrics(pnl, bars_per_year)
        m["requested_delay_s"] = d
        m["effective_delay_s"] = float(fills["effective_delay_s"].median())
        m["skipped"] = ""
        # Slippage of the delay: how far the price moved between decision and fill, in the
        # direction we were about to take. This is the mechanism behind any decay seen.
        if "decision_price" in fills:
            moved = (fills["price"] - fills["decision_price"]) / fills["decision_price"]
            m["delay_slippage_bps"] = float((moved * np.sign(fills["position"])).mean() * 1e4)
        rows.append(m)
    return pd.DataFrame(rows)


def survival_threshold(curve: pd.DataFrame, metric: str = "sharpe") -> tuple:
    """(threshold, conservative target, censored) in seconds, from the measured curve.

    The threshold is the largest delay whose metric is still positive. A curve that is negative
    everywhere returns (None, None, False): there is nothing to be fast enough for.

    CENSORED matters. If the last positive bucket is also the longest delay tested, the curve
    never crossed zero inside the range and the true threshold is somewhere beyond it. Printing
    that as "48 hours" would be reporting the edge of the ruler as a measurement, so it is
    flagged and must be read as "at least".
    """
    c = curve[curve["skipped"] == ""].sort_values("effective_delay_s")
    if c.empty or not (c[metric] > 0).any():
        return None, None, False
    last_positive = float(c[c[metric] > 0]["effective_delay_s"].max())
    censored = bool(last_positive >= float(c["effective_delay_s"].max()))
    return last_positive, last_positive * SAFETY_FACTOR, censored


def feasible_from_here(threshold_s: float | None,
                       order_path_ms: dict | None = None) -> tuple[bool, str]:
    """Can this machine, on this connection, actually operate inside the threshold?"""
    p = order_path_ms or MEASURED_ORDER_PATH_MS
    if threshold_s is None:
        return False, "no delay bucket shows a positive edge, so speed is not the problem"
    target = threshold_s * SAFETY_FACTOR
    worst = p["max"] / 1000.0
    typical = p["mean"] / 1000.0
    if target < typical:
        return False, (f"needs to act within {target:.3g}s but this machine's typical order "
                       f"path is {typical:.3g}s: INFRASTRUCTURE_INFEASIBLE from here")
    if target < worst:
        return True, (f"workable on a typical {typical:.3g}s path, but the observed worst case "
                      f"of {worst:.3g}s exceeds the {target:.3g}s target: expect occasional misses")
    return True, (f"comfortable: target {target:.3g}s against a worst observed order path of "
                  f"{worst:.3g}s")
