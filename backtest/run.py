"""Run the MVP research pipeline end-to-end (offline): load bars -> backtest a simple
strategy with the real measured spread -> print a plain-English report.

No live orders. No reactor. Pure analysis over stored data.

    python -m market.bars --symbol EURUSD --period H1 --days 180   # step 1: get data
    python -m backtest.run --symbol EURUSD --period H1 --fast 20 --slow 50
"""
from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from backtest import metrics
from backtest.harness import CostModel, run_backtest
from config import settings
from report.explainer import explain
from strategy.ma_trend import MovingAverageTrend

MARKET_DB = "data/market.db"


def load_bars(symbol: str, period: str) -> pd.DataFrame:
    conn = sqlite3.connect(MARKET_DB)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM bars WHERE symbol=? AND period=? ORDER BY ts_utc",
            conn, params=(symbol.upper(), period.upper()))
    finally:
        conn.close()
    return df


def _pip_size(symbol: str, pip_position: int | None) -> float:
    if pip_position is not None:
        return 10 ** (-pip_position)
    s = symbol.upper()
    return 0.01 if ("JPY" in s or s.startswith("XAU")) else 0.0001


def measured_cost(symbol: str, ref_price: float) -> CostModel:
    """Pull median spread (pips) and pip_position from the telemetry DB; fall back safely."""
    spread_pips, pip_position = None, None
    try:
        c = sqlite3.connect(settings.TELEMETRY_DB)
        row = c.execute("SELECT pip_position FROM symbol_spec WHERE symbol=?",
                        (symbol.upper(),)).fetchone()
        pip_position = row[0] if row else None
        row = c.execute("SELECT median(spread_pips) FROM (SELECT spread_pips FROM ticks "
                        "WHERE symbol=?)", (symbol.upper(),)).fetchone()
        c.close()
    except Exception:  # noqa: BLE001
        pass
    if spread_pips is None:
        # SQLite has no median(); compute in pandas if telemetry ticks exist.
        try:
            c = sqlite3.connect(settings.TELEMETRY_DB)
            sp = pd.read_sql_query("SELECT spread_pips FROM ticks WHERE symbol=?",
                                   c, params=(symbol.upper(),))
            c.close()
            if not sp.empty:
                spread_pips = float(sp["spread_pips"].median())
        except Exception:  # noqa: BLE001
            pass
    if spread_pips is None:
        s = symbol.upper()
        spread_pips = 20.0 if s.startswith("XAU") else (2.0 if "JPY" in s else 1.0)
        print(f"  (no telemetry for {symbol}; using conservative default spread {spread_pips} pips)")
    return CostModel(spread_pips=spread_pips, pip_size=_pip_size(symbol, pip_position),
                     ref_price=ref_price)


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest a simple strategy on stored bars.")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--period", default="H1")
    p.add_argument("--fast", type=int, default=20)
    p.add_argument("--slow", type=int, default=50)
    p.add_argument("--email", action="store_true", help="email the report (needs SMTP in .env)")
    p.add_argument("--to", nargs="*", default=None, help="override recipients")
    args = p.parse_args()

    bars = load_bars(args.symbol, args.period)
    if bars.empty:
        print(f"no bars for {args.symbol} {args.period}. Run: "
              f"python -m market.bars --symbol {args.symbol} --period {args.period}")
        return

    ppy = metrics.BARS_PER_YEAR.get(args.period.upper(), 6240)
    costs = measured_cost(args.symbol, ref_price=float(bars["close"].mean()))
    strat = MovingAverageTrend(args.fast, args.slow)

    result = run_backtest(bars, strat, costs, ppy)

    # Simple out-of-sample tail: last 30%, same strategy, no refitting.
    cut = int(len(bars) * 0.7)
    holdout = run_backtest(bars.iloc[cut:].reset_index(drop=True), strat, costs, ppy).summary

    report = explain(args.symbol, args.period, strat, result, costs, len(bars), holdout)
    print(report)

    if args.email:
        from report import mailer
        subject = f"[Trading Research Engine] {strat.name} on {args.symbol} {args.period}"
        html = ("<div style=\"font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif\">"
                "<pre style=\"font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;"
                "white-space:pre-wrap;line-height:1.5\">" + report + "</pre></div>")
        try:
            mailer.send(subject, report, html, to=args.to)
        except Exception as exc:  # noqa: BLE001
            print(f"\nemail NOT sent: {exc}")


if __name__ == "__main__":
    main()
