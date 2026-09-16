"""Apply the multiple-testing correction to the sweep leaderboard.

A sweep produces a ranked list, and a ranked list is the most dangerous object in this
project. Nineteen of eighty-seven D1 pairs came out positive on both development and
holdout, which sounds like nineteen findings and is in fact what eighty-seven coin flips
looks like: chance alone predicts 21.8.

The deflated Sharpe ratio is the arithmetic that says so. It asks: given that N candidates
were tried, and given how much their Sharpes varied, how surprising is the best one? The
expected maximum Sharpe from N zero-skill trials grows with N, so a search that has tried
a hundred things must clear a far higher bar than one that tried two.

**N is the honest count, not the shortlist.** It is every candidate this engine has ever
scored: every sweep row at any frequency, plus every trial in the failure registry. Using
the number of survivors here would be circular, and using this run's count alone would
forgive every earlier search. That was a real bug in `research/experiment.py` once, where
N was `len(tested)` and the bar came out orders of magnitude too low.

Only pairs positive on BOTH windows are re-run, because nothing else can pass and the
re-run is the expensive part. Each is re-fitted from scratch through `walk_forward_refit`
so the holdout return series is genuine rather than reconstructed from stored summaries:
skew and kurtosis matter to the PSR and cannot be recovered from a Sharpe.

    python -m scripts.deflate_sweep --period D1
"""
from __future__ import annotations

import argparse
import gc
import sqlite3
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np

from backtest import walkforward as wf
from backtest.metrics import BARS_PER_YEAR
from backtest.run import load_bars, measured_cost
from strategy.registry import build_strategy

DB = "data/research.db"
MIN_DSR = 0.95          # the same bar the research loop uses


def honest_n(conn: sqlite3.Connection) -> tuple[int, dict]:
    """Every candidate ever scored, across every frequency and every run."""
    sweep = list(conn.execute("SELECT count(*) FROM sweep_results"))[0][0]
    registry = 0
    try:
        registry = list(conn.execute("SELECT count(*) FROM trials"))[0][0]
    except sqlite3.Error:
        pass                                   # registry table may not exist yet
    return max(sweep + registry, 2), {"sweep_rows": sweep, "registry_trials": registry}


def sharpe_spread(conn: sqlite3.Connection, period: str) -> float:
    """Standard deviation of PER-OBSERVATION Sharpes across every evaluable trial.

    Stored Sharpes are annualised; the deflation works per observation, so they are divided
    back down by sqrt(bars per year). Mixing the two units would inflate the threshold by a
    factor of about eighty at H1 and sixteen at D1, and silently fail everything.
    """
    ppy = BARS_PER_YEAR.get(period.upper(), 6240)
    vals = [r[0] / np.sqrt(ppy) for r in conn.execute(
        "SELECT dev_sharpe FROM sweep_results WHERE period=? AND evaluable=1 "
        "AND dev_sharpe IS NOT NULL", (period.upper(),))]
    return float(np.std(vals)) if len(vals) > 1 else 0.1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):        # pragma: no cover
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--period", default="D1")
    ap.add_argument("--min-dsr", type=float, default=MIN_DSR)
    a = ap.parse_args()
    period = a.period.upper()

    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS sweep_dsr ("
                 "symbol TEXT, model TEXT, period TEXT, dsr REAL, holdout_sharpe REAL, "
                 "n_trials INTEGER, sharpe_std REAL, verdict TEXT, "
                 "PRIMARY KEY (symbol, model, period))")

    n, parts = honest_n(conn)
    spread = sharpe_spread(conn, period)
    sr0 = wf.expected_max_sharpe(spread, n)
    print(f"\ndeflating {period} against N = {n:,} candidates ever scored "
          f"({parts['sweep_rows']} sweep rows + {parts['registry_trials']} registry trials)")
    print(f"per-observation Sharpe spread across trials: {spread:.5f}")
    print(f"a zero-skill search of this size is EXPECTED to produce a best per-observation "
          f"Sharpe of {sr0:.5f}\n  (annualised: {sr0 * np.sqrt(BARS_PER_YEAR.get(period, 6240)):.3f}) "
          f"purely by luck. That is the bar.\n")

    cands = list(conn.execute(
        "SELECT symbol, model, dev_sharpe, holdout_sharpe FROM sweep_results "
        "WHERE period=? AND evaluable=1 AND dev_sharpe>0 AND holdout_sharpe>0 "
        "ORDER BY holdout_sharpe DESC", (period,)))
    if not cands:
        print("nothing positive on both windows; nothing to deflate")
        return 0

    print(f"{'symbol':<9}{'model':<15}{'holdout':>9}{'DSR oof':>8}{'DSR hld':>8}   verdict")
    print("-" * 66)
    passed = 0
    for sym, model, dev_s, hold_s in cands:
        bars = load_bars(sym, period)
        if bars.empty:
            print(f"{sym:<9}{model:<15}{'--':>9}{'--':>8}   no bars")
            continue
        costs = measured_cost(sym, ref_price=float(bars["close"].mean()))
        try:
            r = wf.walk_forward_refit(bars, lambda m=model: build_strategy(m, {}), costs,
                                      period)
        except Exception as exc:                # noqa: BLE001
            print(f"{sym:<9}{model:<15}{'--':>9}{'--':>8}   re-run failed: "
                  f"{type(exc).__name__}")
            del bars; gc.collect()
            continue
        # Deflate BOTH out-of-sample records rather than choosing one. The out-of-fold
        # development series has far more observations (every bar scored by a model that
        # never saw it); the holdout is smaller but was touched exactly once. A candidate
        # worth anything should survive both, and reporting only the friendlier of the two
        # is how a leaderboard flatters itself.
        dsr_oof = wf.deflated_sharpe_ratio(r.get("dev_net_returns"), n, spread)
        hr = r.get("holdout_net_returns")
        dsr_hold = (wf.deflated_sharpe_ratio(hr, n, spread)
                    if hr is not None and len(hr) >= 3 else float("nan"))
        dsr = min(dsr_oof, dsr_hold) if dsr_hold == dsr_hold else dsr_oof
        ok = dsr >= a.min_dsr
        passed += ok
        conn.execute("INSERT OR REPLACE INTO sweep_dsr VALUES (?,?,?,?,?,?,?,?)",
                     (sym, model, period, dsr, hold_s, n, spread,
                      "PASS" if ok else "FAIL"))
        conn.commit()
        print(f"{sym:<9}{model:<15}{hold_s:>9.3f}{dsr_oof:>8.3f}{dsr_hold:>8.3f}   "
              f"{'PASS' if ok else 'fails the bar'}")
        del bars; gc.collect()

    print(f"\n{passed} of {len(cands)} cleared DSR >= {a.min_dsr} against N = {n:,}.")
    if passed == 0:
        print("\nThat is the result, and it is not a disappointment: it is the correction\n"
              "working. A leaderboard of nineteen from eighty-seven coin flips is what\n"
              "chance produces, and the deflation is the arithmetic that refuses to call it\n"
              "an edge. Nothing here justifies risking money.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
