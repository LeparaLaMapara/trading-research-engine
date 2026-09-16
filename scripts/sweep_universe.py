"""Score every fitted model against every instrument, persisting as it goes.

Run:  python -m scripts.sweep_universe
      python -m scripts.sweep_universe --report      # read back what has been done

Two design decisions, both learned the hard way last night.

**Every result is written the moment it exists.** The first attempt at this sweep printed
only at the end, ran for an hour, and was killed. An hour of compute produced nothing. Each
(symbol, model) pair is now committed to SQLite immediately, and a re-run skips pairs already
done, so the work is resumable rather than atomic.

**One symbol in memory at a time.** An unrelated training job on this machine was holding
~6GB and turning large allocations into MemoryError. Bars are loaded per symbol and released
before the next, so a loaded machine slows the sweep down instead of killing it.

What is recorded, per pair: out-of-fold Sharpe, holdout Sharpe, fold coverage, the fitted
parameters per fold, and whether the pair was EVALUABLE at all. That last column is the one
that matters most and the easiest to lose: a model whose fitted lookback exceeds the test
window produces almost no positions and scores a meaningless 0.0. Not evaluated is not the
same as evaluated and failed, and collapsing them would quietly poison both the leaderboard
and the multiple-testing correction.
"""
from __future__ import annotations

import argparse
import gc
import json
import sqlite3
import sys
import time
import warnings

warnings.filterwarnings("ignore")

from backtest import walkforward as wf
from backtest.run import load_bars, measured_cost
from research.cost_ceiling import probe_cost
from config.instruments import asset_class_of, universe
from strategy.registry import build_strategy

DB = "data/research.db"
DEFAULT_MODELS = ("ou_reversion", "kalman_level", "ma_trend", "vol_scaled")
#: Minimum history per period. D1 will never have 5,000 bars: twelve years is about 3,100,
#: and demanding H1 depth from a daily series would silently skip the entire universe.
MIN_BARS = {"M15": 20000, "H1": 5000, "H4": 3000, "D1": 750, "W1": 200}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sweep_results (
    symbol        TEXT NOT NULL,
    asset_class   TEXT,
    model         TEXT NOT NULL,
    n_bars        INTEGER,
    evaluable     INTEGER NOT NULL,
    why_not       TEXT,
    dev_sharpe    REAL,
    holdout_sharpe REAL,
    folds_evaluated INTEGER,
    folds_attempted INTEGER,
    active_bars   TEXT,
    fold_params   TEXT,
    ran_at        REAL,
    period        TEXT NOT NULL DEFAULT 'H1',
    cost_sr       REAL,
    PRIMARY KEY (symbol, model, period)
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    # Migrate the pre-period table rather than dropping it. The 27 H1 results already in
    # there are the evidence behind "1 positive where chance predicts 7" and re-earning
    # them would cost hours. Old rows are stamped H1, which is what they were.
    have = {r[1] for r in c.execute("PRAGMA table_info(sweep_results)")}
    if have and "period" not in have:
        cols = ",".join(sorted(have))
        c.execute("ALTER TABLE sweep_results RENAME TO sweep_results_pre_period")
        c.executescript(SCHEMA)
        c.execute(f"INSERT INTO sweep_results ({cols}, period) "
                  f"SELECT {cols}, 'H1' FROM sweep_results_pre_period")
        c.execute("DROP TABLE sweep_results_pre_period")
        c.commit()
        print("migrated sweep_results: existing rows stamped period=H1", flush=True)
    c.executescript(SCHEMA)
    return c


def done_pairs(conn: sqlite3.Connection, period: str) -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in conn.execute(
        "SELECT symbol, model FROM sweep_results WHERE period=?", (period.upper(),))}


def record(conn: sqlite3.Connection, **row) -> None:
    cols = ",".join(row)
    conn.execute(f"INSERT OR REPLACE INTO sweep_results ({cols}) "
                 f"VALUES ({','.join(':' + c for c in row)})", row)
    conn.commit()          # commit per pair: a kill must never cost more than one result


def evaluate(symbol: str, model: str, bars, costs, period: str) -> dict:
    # COST CEILING FIRST. A rule too expensive to run is deleted before it is fitted, so it
    # never reaches the leaderboard and cannot win on a fold where noise paid its spread.
    # Recorded as a result, not skipped: it was a candidate and it counts against N.
    est = probe_cost(bars, lambda: build_strategy(model, {}), costs, period)
    if est.evaluable and not est.affordable:
        return {"evaluable": 0, "why_not": f"too expensive: {est.reason}",
                "dev_sharpe": None, "holdout_sharpe": None, "cost_sr": est.cost_sr,
                "folds_evaluated": 0, "folds_attempted": 0,
                "active_bars": "[]", "fold_params": "[]"}
    r = wf.walk_forward_refit(bars, lambda: build_strategy(model, {}), costs, period)
    if not r.get("evaluable", False):
        return {"evaluable": 0, "why_not": r.get("why_not", "unknown"),
                "dev_sharpe": None, "holdout_sharpe": None, "cost_sr": est.cost_sr,
                "folds_evaluated": 0, "folds_attempted": len(r.get("fold_active_bars", [])),
                "active_bars": json.dumps(r.get("fold_active_bars", [])),
                "fold_params": json.dumps(r.get("fold_params", []), default=str)}
    hold = r.get("holdout_summary")
    return {"evaluable": 1, "why_not": None, "cost_sr": est.cost_sr,
            "dev_sharpe": r["dev_summary"]["sharpe"],
            "holdout_sharpe": hold["sharpe"] if hold else None,
            "folds_evaluated": r.get("folds_evaluated"),
            "folds_attempted": r.get("folds_attempted"),
            "active_bars": json.dumps(r.get("fold_active_bars", [])),
            "fold_params": json.dumps(r.get("fold_params", []), default=str)}


def run(only: list[str] | None, force: bool, period: str = "H1",
        models: tuple[str, ...] = DEFAULT_MODELS) -> int:
    period = period.upper()
    conn = _conn()
    already = set() if force else done_pairs(conn, period)
    symbols = only or universe()
    todo = [(s, m) for s in symbols for m in models if (s, m) not in already]
    print(f"{len(todo)} pairs to evaluate ({len(already)} already done)\n", flush=True)

    for sym in symbols:
        pending = [m for m in models if (sym, m) not in already]
        if not pending:
            continue
        try:
            bars = load_bars(sym, period)
        except Exception as exc:  # noqa: BLE001
            print(f"{sym:<9} load failed: {exc}", flush=True)
            continue
        floor = MIN_BARS.get(period, 1000)
        if len(bars) < floor:
            print(f"{sym:<9} only {len(bars):,} {period} bars (need {floor:,}), skipped", flush=True)
            continue
        costs = measured_cost(sym, ref_price=float(bars["close"].mean()))
        for model in pending:
            t0 = time.time()
            try:
                res = evaluate(sym, model, bars, costs, period)
            except MemoryError:
                print(f"{sym:<9} {model:<14} MemoryError, machine is loaded; skipping",
                      flush=True)
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"{sym:<9} {model:<14} FAILED: {type(exc).__name__}: {exc}", flush=True)
                continue
            record(conn, symbol=sym, asset_class=asset_class_of(sym), model=model,
                   period=period, n_bars=len(bars), ran_at=time.time(), **res)
            if res["evaluable"]:
                print(f"{sym:<9} {model:<14} dev {res['dev_sharpe']:>7.3f}  "
                      f"holdout {str(res['holdout_sharpe'])[:7]:>7}  "
                      f"{res['folds_evaluated']}/{res['folds_attempted']} folds  "
                      f"({time.time()-t0:.0f}s)", flush=True)
            else:
                print(f"{sym:<9} {model:<14} NOT EVALUABLE  ({time.time()-t0:.0f}s)",
                      flush=True)
        del bars
        gc.collect()          # the machine is shared; give the memory back between symbols
    conn.close()
    return 0


def report(period: str | None = None) -> int:
    conn = _conn()
    rows = list(conn.execute(
        "SELECT symbol, asset_class, model, evaluable, dev_sharpe, holdout_sharpe, "
        "folds_evaluated, folds_attempted, why_not, period FROM sweep_results "
        + (f"WHERE period='{period.upper()}' " if period else "") +
        "ORDER BY evaluable DESC, holdout_sharpe DESC"))
    if not rows:
        print("no results yet")
        return 0
    print(f"{'symbol':<9}{'class':<11}{'model':<15}{'dev OOF':>9}{'holdout':>9}  folds")
    print("-" * 72)
    for s, c, m, ev, d, h, fe, fa, why, per in rows:
        if not ev:
            print(f"{s:<9}{c or '':<11}{m:<15}{'--':>9}{'--':>9}  NOT EVALUABLE")
            continue
        print(f"{s:<9}{c or '':<11}{m:<15}{d:>9.3f}"
              f"{(f'{h:.3f}' if h is not None else '--'):>9}  {fe}/{fa}")

    ev = [r for r in rows if r[3]]
    both_pos = [r for r in ev if r[4] and r[4] > 0 and r[5] and r[5] > 0]
    # THE BASELINE, printed next to the count and never without it. If dev and holdout
    # Sharpes were pure noise, symmetric about zero and independent, a quarter of pairs
    # would be positive on both by luck alone. A bare count reads as a result when it is a
    # coin-flip tally, and this report has already been read that way once.
    expected = 0.25 * len(ev)
    print(f"\n{len(rows)} pairs recorded, {len(ev)} evaluable, "
          f"{len(both_pos)} positive on BOTH development and holdout")
    print(f"   chance alone predicts {expected:.1f} of {len(ev)}. Observed {len(both_pos)} is "
          + ("BELOW chance: costs are eating the signal."
             if len(both_pos) < expected * 0.75 else
             "ABOVE chance. Worth a closer look, not yet evidence."
             if len(both_pos) > expected * 1.5 else
             "AT chance: no evidence of edge either way."))
    print("   Positive on both is the price of ADMISSION, not a pass. Nothing here is an "
          "edge until\n   it clears the deflated-Sharpe bar against the honest trial count.")
    for r in both_pos:
        print(f"   {r[0]} {r[2]}: dev {r[4]:.3f}, holdout {r[5]:.3f}")
    conn.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", action="store_true", help="print what has been recorded")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--force", action="store_true", help="re-run pairs already recorded")
    p.add_argument("--period", default="H1")
    p.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    a = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    return (report(a.period if a.report else None) if a.report
            else run(a.symbols, a.force, a.period, tuple(a.models)))


if __name__ == "__main__":
    raise SystemExit(main())
