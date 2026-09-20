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
from config.instruments import asset_class_of
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


#: Conservative round-trip spread assumptions, in basis points of price, for instruments
#: with no measured telemetry. Only a fallback: anything being traded gets measured first.
_DEFAULT_SPREAD_BPS = {
    "fx_major": 2.0,    # EURUSD ~0.2 pips on 1.10 is ~1.8 bps
    "fx_cross": 3.0,
    "metal": 3.0,       # XAUUSD ~0.30 on 2000 is ~1.5 bps
    "index": 2.0,
    "energy": 5.0,      # XTIUSD ~0.03 on 75 is ~4 bps
    "crypto": 15.0,     # BTCUSD tens of dollars on tens of thousands; ADA far wider
}


def _pip_size(symbol: str, pip_position: int | None) -> float:
    if pip_position is not None:
        return 10 ** (-pip_position)
    s = symbol.upper()
    return 0.01 if ("JPY" in s or s.startswith("XAU")) else 0.0001


def measured_cost(symbol: str, ref_price: float) -> CostModel:
    """Round-trip cost for one symbol, measured from telemetry where the data supports it.

    RED TEAM 2026-09-20: this function was DEAD. A `c.close()` sat between two queries that
    shared the connection, the resulting ProgrammingError was swallowed by a bare `except`,
    and every symbol fell through to the hardcoded class default while the code, the comments
    and the published tables all claimed the number was measured. Two lessons are baked in
    below: the connection is held by a context manager, and a failure to measure is PRINTED,
    because a silent fallback is indistinguishable from a measurement until someone audits it.
    """
    spread_pips, pip_position, source = None, None, "default"
    MIN_TICKS, MIN_HOURS = 200, 8
    try:
        with sqlite3.connect(settings.TELEMETRY_DB) as c:
            row = c.execute("SELECT pip_position FROM symbol_spec WHERE symbol=?",
                            (symbol.upper(),)).fetchone()
            pip_position = row[0] if row else None
            # Admissible quotes only. The data-quality audit found 7.9% of logged ticks carry
            # bid exactly equal to ask and 32.6% update one side against a stale other side.
            sp = pd.read_sql_query(
                "SELECT spread_pips, hour_of_week FROM ticks WHERE symbol=? "
                "AND side='bid+ask' AND spread_pips > 0", c, params=(symbol.upper(),))
        if len(sp) >= MIN_TICKS:
            covered = int(sp["hour_of_week"].nunique())
            if covered >= MIN_HOURS:
                spread_pips = float(sp["spread_pips"].median())
                source = f"measured median over {covered} hours-of-week, n={len(sp)}"
            else:
                # The recorder ran mostly inside the London/New York overlap, the cheapest hour
                # of the day, so a median from it understates every other hour. The 75th
                # percentile is a hedge, NOT a measurement of the unobserved hours: the red
                # team showed it still understates the 21:00 rollover by 4x to 33x.
                spread_pips = float(sp["spread_pips"].quantile(0.75))
                source = (f"p75 hedge: only {covered} hours-of-week observed, n={len(sp)}; "
                          f"understates unobserved hours")
        elif not sp.empty:
            print(f"  [cost] {symbol}: only {len(sp)} admissible ticks (<{MIN_TICKS}); "
                  f"falling back to the class default")
    except Exception as exc:  # noqa: BLE001
        # Loud on purpose. This is the exact silence that hid the dead code above.
        print(f"  [cost] {symbol}: telemetry unreadable ({type(exc).__name__}: {exc}); "
              f"falling back to the class default")

    if spread_pips is None:
        # FALLBACK, in basis points of PRICE rather than in pips.
        #
        # The previous version defaulted to "1.0 pips" for anything that was not gold or a
        # JPY cross, and then priced it with the FX pip convention of 0.0001. On BTCUSD at
        # ~$30,000 that is 1.0 * 0.0001 / 30000, about two parts per BILLION: a spread of
        # effectively zero on the single widest-spread instrument in the universe. Seventeen
        # of twenty-four instruments were being costed that way, which made every one of them
        # look affordable no matter what it did.
        #
        # A pip is an FX convention and it does not transfer. Basis points of price do, so
        # the defaults below are quoted that way and converted back into this symbol's own
        # pip units. They are deliberately pessimistic: a fallback that flatters a strategy
        # is worse than no fallback at all.
        bps = _DEFAULT_SPREAD_BPS.get(asset_class_of(symbol) or "", 10.0)
        ps = _pip_size(symbol, pip_position)
        spread_pips = (bps * 1e-4) * ref_price / ps
        print(f"  (no telemetry for {symbol}; assuming {bps:g} bps of price = "
              f"{spread_pips:.2f} pips at {ref_price:.2f})")
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
