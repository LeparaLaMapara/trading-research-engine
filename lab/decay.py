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

#: Measured from this machine: ProtoOAVersionReq round trip, 1,967 samples (telemetry.db).
#:
#: This is NOT a physical minimum. It is the observed performance of ONE location, network,
#: broker and architecture. A VPS near the broker, a different venue, or a different transport
#: would produce different numbers, and the right time to find out is when a validated strategy
#: shows economic sensitivity to this range, not before.
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
        eff = fills["effective_delay_s"]
        m["effective_delay_s"] = float(eff.median())
        # A bucket is not one delay. Over a weekend a "24h" request fills 36 to 96 hours late,
        # so the spread is reported alongside the median rather than hidden behind it.
        m["effective_delay_p90_s"] = float(eff.quantile(0.90))
        m["effective_delay_max_s"] = float(eff.max())
        m["pct_over_2x_requested"] = float((eff > 2 * max(d, 1)).mean() * 100) if d else 0.0
        m["skipped"] = ""
        # Slippage of the delay: how far the price moved between decision and fill, in the
        # direction we were about to take. This is the mechanism behind any decay seen.
        if "decision_price" in fills:
            moved = (fills["price"] - fills["decision_price"]) / fills["decision_price"]
            m["delay_slippage_bps"] = float((moved * np.sign(fills["position"])).mean() * 1e4)
        rows.append(m)
    return pd.DataFrame(rows)


def crossing_bracket(curve: pd.DataFrame, metric: str = "sharpe") -> dict:
    """Where the edge crosses zero, as an INTERVAL, because that is what was measured.

    Reporting "threshold = 12h" when 12h was positive and 24h negative claims a precision the
    grid does not contain: the crossing is somewhere in between. Statuses:

      bracketed      the crossing lies in (lo, hi); refine to narrow it
      censored_right positive at every delay tested, so the threshold is beyond the grid
      no_edge        not positive anywhere, including zero delay
    """
    c = curve[curve["skipped"] == ""].sort_values("effective_delay_s")
    if c.empty or not (c[metric] > 0).any():
        return {"status": "no_edge", "lo": None, "hi": None}
    pos = c[c[metric] > 0]["effective_delay_s"]
    last_pos = float(pos.max())
    after = c[c["effective_delay_s"] > last_pos]
    if after.empty:
        return {"status": "censored_right", "lo": last_pos, "hi": float("inf")}
    return {"status": "bracketed", "lo": last_pos,
            "hi": float(after["effective_delay_s"].min())}


def refine_bracket(signals, exec_bars, bracket: dict, cost_per_turnover: float,
                   financing_per_day: float = 0.0, exec_period: str = "H1",
                   bars_per_year: float = 260.0, rounds: int = 3,
                   metric: str = "sharpe") -> tuple[pd.DataFrame, dict]:
    """Bisect the crossing interval, at most `rounds` times, never finer than the data.

    Adaptive compute: extra runs are spent ONLY where the curve transitions, not uniformly
    across a grid that is flat at both ends.
    """
    from lab.replay import BAR_SECONDS
    step = BAR_SECONDS[exec_period.upper()]
    extra = []
    lo, hi = bracket.get("lo"), bracket.get("hi")
    if bracket.get("status") != "bracketed":
        return pd.DataFrame(), bracket
    for _ in range(rounds):
        mid = round((lo + hi) / 2.0 / step) * step
        if mid <= lo or mid >= hi:          # the grid is already at the data's resolution
            break
        row = decay_curve(signals, exec_bars, [mid], cost_per_turnover, financing_per_day,
                          exec_period, bars_per_year)
        extra.append(row)
        r = row.iloc[0]
        if r.get("skipped") or not np.isfinite(r.get(metric, np.nan)):
            break
        if r[metric] > 0:
            lo = float(r["effective_delay_s"])
        else:
            hi = float(r["effective_delay_s"])
    out = pd.concat(extra, ignore_index=True) if extra else pd.DataFrame()
    return out, {"status": "bracketed", "lo": lo, "hi": hi,
                 "resolution_limit_s": float(step)}


def operating_target(bracket: dict) -> float | None:
    """Conservative target: a fraction of the PESSIMISTIC end of the bracket, never the middle
    and never the optimistic end."""
    lo = bracket.get("lo")
    return None if lo is None else float(lo) * SAFETY_FACTOR


def bootstrap_metric_ci(pnl_net: np.ndarray, bars_per_year: float, block: int = 20,
                        reps: int = 2000, seed: int = 7) -> tuple[float, float]:
    """Block bootstrap CI for the Sharpe of one bucket: is the sign even reliable?"""
    rng = np.random.default_rng(seed)
    n = len(pnl_net)
    if n < block * 3:
        return float("nan"), float("nan")
    out = np.empty(reps)
    for i in range(reps):
        starts = rng.integers(0, n - block, size=n // block + 1)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        s = pnl_net[idx]
        out[i] = s.mean() / s.std() * np.sqrt(bars_per_year) if s.std() > 0 else 0.0
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def bootstrap_crossing(signals, exec_bars, delays_s, cost_per_turnover,
                       financing_per_day=0.0, exec_period="H1", bars_per_year=260.0,
                       reps: int = 300, block: int = 20, seed: int = 11) -> dict:
    """How reproducible is the crossing? Resample the P&L and see where the curve crosses.

    RED TEAM 2026-09-20: the published bracket (18h, 20h) was the crossing of ONE realisation
    of a curve whose buckets each rest on 39 trades. Under a block bootstrap the crossing point
    moves across the whole grid and only 2% of replicates land in that bracket. A bracket
    without this interval is false precision, so the runner now reports both.

    The SAME block indices are applied to every bucket in a replicate, because the buckets are
    the same strategy at different delays and are heavily correlated; resampling them
    independently would manufacture crossings that no single history could produce.
    """
    from lab.replay import ResolutionError, fills_for_delay, pnl_from_fills
    series = {}
    for d in delays_s:
        try:
            f = fills_for_delay(signals, exec_bars, d, exec_period)
        except ResolutionError:
            continue
        if len(f) < 30:
            continue
        pnl = pnl_from_fills(f, cost_per_turnover, financing_per_day)
        series[float(f["effective_delay_s"].median())] = pnl["net"].to_numpy()
    if len(series) < 3:
        return {"reps": 0, "note": "not enough priceable buckets to bootstrap"}

    keys = sorted(series)
    n = min(len(v) for v in series.values())
    rng = np.random.default_rng(seed)
    crossings, never, none_positive = [], 0, 0
    for _ in range(reps):
        starts = rng.integers(0, max(n - block, 1), size=n // block + 1)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        sharpes = []
        for k in keys:
            x = series[k][:n][idx]
            sharpes.append(x.mean() / x.std() * np.sqrt(bars_per_year) if x.std() > 0 else 0.0)
        pos = [k for k, sh in zip(keys, sharpes) if sh > 0]
        if not pos:
            none_positive += 1
            continue
        last_pos = max(pos)
        if last_pos >= keys[-1]:
            never += 1
            continue
        crossings.append(last_pos)
    out = {"reps": reps, "never_crossed_pct": 100.0 * never / reps,
           "no_edge_at_all_pct": 100.0 * none_positive / reps,
           "crossed_pct": 100.0 * len(crossings) / reps}
    if crossings:
        a = np.array(crossings)
        out.update({"crossing_p5_s": float(np.percentile(a, 5)),
                    "crossing_median_s": float(np.median(a)),
                    "crossing_p95_s": float(np.percentile(a, 95))})
    return out


def survival_threshold(curve: pd.DataFrame, metric: str = "sharpe") -> tuple:
    """Kept for callers that want a single number. Prefer crossing_bracket: this returns the
    PESSIMISTIC end of the bracket, which is the largest delay actually shown to work."""
    b = crossing_bracket(curve, metric)
    if b["status"] == "no_edge":
        return None, None, False
    return b["lo"], operating_target(b), b["status"] == "censored_right"


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
        return False, (f"needs to act within {target:.3g}s but the CURRENT path (this house, "
                       f"this broker, this architecture) is typically {typical:.3g}s: "
                       f"INFRASTRUCTURE_INFEASIBLE as configured. Not a law of nature: hosting "
                       f"nearer the venue would have to be measured, and is only worth costing "
                       f"if the edge is otherwise validated")
    if target < worst:
        return True, (f"workable on a typical {typical:.3g}s path, but the observed worst case "
                      f"of {worst:.3g}s exceeds the {target:.3g}s target: expect occasional misses")
    return True, (f"comfortable: target {target:.3g}s against a worst observed order path of "
                  f"{worst:.3g}s")
