"""Score E09 (docs/programme/E09-eth-funding-short-prereg.md): short Ethereum only when
perpetual funding is high. Written after the pre-registration was pushed (e9f2ac5).

    gh workflow run databricks-run.yml -f module=scripts.e09_funding_short

Writes docs/results/E09-eth-funding-short.json and records one trial.
"""
from __future__ import annotations

import json
import sqlite3
import time

import numpy as np
import pandas as pd

from backtest.walkforward import deflated_sharpe_ratio

OUT = "docs/results/E09-eth-funding-short.json"
DAY = 86400
COST = 12.9e-4                   # round trip: measured spread 12.21 bps + 0.7 bps commission
HOLD, STOP_SIGMAS, VOL_DAYS = 30, 4.0, 20
PRINTS, PCTL, LOOKBACK, MIN_HIST = 21, 80, 365, 180
DECIDE = ("2022-02-01", "2026-08-31")
REPLICATE = ("2019-11-01", "2022-01-31")
N_NULL, N_BOOT, N_TRIALS, MIN_EPISODES = 10_000, 10_000, 307, 8


def bars() -> pd.DataFrame:
    """ETHUSD daily bars indexed by their CLOSE time (the broker stamps a bar at its open)."""
    with sqlite3.connect("data/market.db") as c:
        b = pd.read_sql_query("SELECT ts_utc, open, high, low, close FROM bars WHERE "
                              "symbol='ETHUSD' AND period='D1' ORDER BY ts_utc", c)
    b["close_ts"] = pd.to_datetime(b["ts_utc"] + DAY, unit="s", utc=True)
    return b.set_index("close_ts")[["open", "high", "low", "close"]]


def funding_signal(b: pd.DataFrame, venue: str, symbol: str) -> pd.DataFrame:
    """F at each close (mean of the last 21 funding prints at or before it, annualised) and
    High (F above the 80th percentile of F over the preceding 365 days, 180 days minimum)."""
    f = pd.read_parquet("data/external/funding.parquet")
    f = f[(f["venue"] == venue) & (f["symbol"] == symbol)].sort_values("ts")
    ts, rate = f["ts"].to_numpy(), f["rate"].to_numpy()
    idx = np.searchsorted(ts, b.index.to_numpy(), side="right")     # prints at or before close
    F = np.array([rate[max(0, i - PRINTS):i].mean() * 3 * 365 if i >= PRINTS else np.nan
                  for i in idx])
    out = pd.DataFrame({"F": F}, index=b.index)
    high = []
    for t, v in zip(out.index, out["F"]):
        past = out["F"][(out.index < t) & (out.index >= t - pd.Timedelta(days=LOOKBACK))].dropna()
        high.append(bool(len(past) >= MIN_HIST and not np.isnan(v)
                         and v > np.percentile(past, PCTL)))
    out["high"] = high
    return out


def episode(b: pd.DataFrame, i: int, cost: float) -> dict:
    """A short opened at close i, held 30 closes or until the stop. Returns its path."""
    closes, highs, opens = b["close"].to_numpy(), b["high"].to_numpy(), b["open"].to_numpy()
    p0 = closes[i]
    rets = pd.Series(closes[max(0, i - VOL_DAYS):i + 1]).pct_change().dropna()
    sigma = float(rets.std()) if len(rets) > 2 else 0.05
    stop = p0 * (1 + STOP_SIGMAS * sigma)
    daily, prev = [], p0
    end = min(i + HOLD, len(b) - 1)
    j = i
    for j in range(i + 1, end + 1):
        if highs[j] >= stop:                         # stopped: a gap up fills at the open
            px = max(opens[j], stop)
            daily.append((prev - px) / prev)
            return {"start": i, "exit": j, "stopped": True, "daily": daily,
                    "net": (p0 - px) / p0 - cost}
        daily.append((prev - closes[j]) / prev)
        prev = closes[j]
    return {"start": i, "exit": j, "stopped": False, "daily": daily,
            "net": (p0 - closes[j]) / p0 - cost}


def run_rule(b: pd.DataFrame, sig: pd.DataFrame, window: tuple[str, str], cost: float):
    lo, hi = pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC") + pd.Timedelta(days=1)
    inside = np.where((b.index >= lo) & (b.index < hi))[0]
    last = inside[-1]
    eps, i = [], inside[0]
    while i <= last:
        if sig["high"].iloc[i]:
            e = episode(b.iloc[:last + 1], i, cost)        # marked to market at window end
            eps.append(e)
            i = e["exit"] + (0 if e["stopped"] else 1)     # re-enter at the next close
        else:
            i += 1
    return eps, inside


def daily_pnl(eps: list[dict], inside: np.ndarray, cost: float) -> pd.Series:
    pnl = pd.Series(0.0, index=range(inside[0], inside[-1] + 1))
    for e in eps:
        for k, r in enumerate(e["daily"], start=1):
            pnl[e["start"] + k] = pnl.get(e["start"] + k, 0.0) + r
        pnl[e["start"]] -= cost / 2
        pnl[e["exit"]] -= cost / 2
    return pnl


def sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0


def random_timing(b, inside, k, cost, seed) -> float:
    """Mean net return of k non-overlapping 30-day shorts at random starts in the window."""
    rng = np.random.default_rng(seed)
    starts, taken = [], np.zeros(len(b), dtype=bool)
    cand = inside[inside <= inside[-1] - HOLD]
    for _ in range(k * 50):
        if len(starts) == k:
            break
        s = int(rng.choice(cand))
        if not taken[s:s + HOLD + 1].any():
            taken[s:s + HOLD + 1] = True
            starts.append(s)
    return float(np.mean([episode(b, s, cost)["net"] for s in starts])) if starts else 0.0


def score(b, sig, window, cost=COST, full=True) -> dict:
    eps, inside = run_rule(b, sig, window, cost)
    nets = np.array([e["net"] for e in eps])
    pnl = daily_pnl(eps, inside, cost)
    out = {"window": list(window), "days": int(len(pnl)), "episodes": len(eps),
           "stopped": int(sum(e["stopped"] for e in eps)),
           "net_return_sum": round(float(nets.sum()), 4) if len(nets) else 0.0,
           "mean_net_per_episode": round(float(nets.mean()), 4) if len(nets) else 0.0,
           "net_sharpe": round(sharpe(pnl), 3),
           "episode_starts": [str(b.index[e["start"]].date()) for e in eps]}
    if not full or not len(eps):
        return out
    nulls = np.array([random_timing(b, inside, len(eps), cost, s) for s in range(N_NULL)])
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(nets, size=len(nets), replace=True).sum() for _ in range(N_BOOT)])
    mid = inside[len(inside) // 2]
    first, second = float(pnl[pnl.index < mid].sum()), float(pnl[pnl.index >= mid].sum())
    double = score(b, sig, window, 2 * cost, full=False)["net_return_sum"]
    shorts_all = -(b["close"].iloc[inside[-1]] / b["close"].iloc[inside[0]] - 1) - cost
    crit = {"C1_net_return_and_sharpe_positive": bool(nets.sum() > 0 and sharpe(pnl) > 0),
            "C2_beats_random_timing_p99": bool(nets.mean() > np.percentile(nulls, 99)),
            "C3_at_least_8_episodes": len(eps) >= MIN_EPISODES,
            "C4_positive_at_double_costs": bool(double > 0),
            "C5_bootstrap_share_at_or_below_zero_under_10pct": bool((boot <= 0).mean() < 0.10),
            "C6_both_halves_positive": bool(first > 0 and second > 0)}
    verdict = ("INCONCLUSIVE" if not crit["C3_at_least_8_episodes"] else
               "PASS" if all(crit.values()) else "FAIL")
    out.update({
        "random_timing_null_p99": round(float(np.percentile(nulls, 99)), 4),
        "random_timing_null_mean": round(float(nulls.mean()), 4),
        "bootstrap_share_at_or_below_zero": round(float((boot <= 0).mean()), 4),
        "net_return_first_half": round(first, 4), "net_return_second_half": round(second, 4),
        "split_day": str(b.index[mid].date()),
        "net_return_sum_double_costs": double,
        "always_short_same_window": round(float(shorts_all), 4),
        "largest_episode_share_of_total": round(float(nets.max() / nets.sum()), 3)
        if nets.sum() > 0 else None,
        f"deflated_sharpe_at_N{N_TRIALS}": round(deflated_sharpe_ratio(
            pnl, N_TRIALS, 1.0 / np.sqrt(len(pnl))), 3),
        "criteria": crit, "verdict": verdict})
    return out


def main() -> int:
    b = bars()
    sig = funding_signal(b, "binance", "ETHUSDT")
    manifest = json.load(open("data/external/manifest.json", encoding="utf-8"))
    res = {"experiment": "E09", "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "funding_sha256": manifest["sources"]["funding"].get("sha256"),
           "deciding": score(b, sig, DECIDE),
           "replication_in_paper_period_reported_only": score(b, sig, REPLICATE, full=False)}
    try:
        sb = funding_signal(b, "bitmex", "ETHUSD")
        res["bitmex_funding_reported_only"] = score(b, sb, DECIDE, full=False)
    except Exception as exc:  # noqa: BLE001 - reported only
        res["bitmex_funding_reported_only"] = {"error": str(exc)}
    res["verdict"] = res["deciding"].get("verdict", "INCONCLUSIVE")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    d = res["deciding"]
    if d["episodes"]:
        from research.registry import FailureRegistry
        pnl_sharpe = d["net_sharpe"] / np.sqrt(365)
        reg = FailureRegistry()
        tid = reg.record_trial("eth_funding_short", {"prints": PRINTS, "pctl": PCTL,
                                                     "hold": HOLD, "stop_sigmas": STOP_SIGMAS},
                               "ETHUSD", "D1", stage="programme_E09",
                               per_obs_sharpe=float(pnl_sharpe), n_bars=d["days"])
        reg.set_trial_dsr(tid, d.get(f"deflated_sharpe_at_N{N_TRIALS}", 0.0))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
