"""Pull deep history for the whole research universe, one symbol at a time.

Six years of H1 is roughly 37,000 bars per instrument, against the 3,000 the engine had.
That is what makes the fitted rungs evaluable at all: rung 6 could not be exercised on 180
days, and every rung above it is hungrier still.

Sequential by design. Each symbol needs its own connection and the broker truncates a single
trendbar response at ~14,000 bars, so `market.bars` walks backwards in chunks. Running these
in parallel would just collect rate limits.

OPERATIONAL CONSTRAINT, learned the hard way: the broker allows ONE authenticated session
per trading account at a time. A second process that authenticates the same account gets
ALREADY_LOGGED_IN, and the failure is silent -- the connection stays up, subscriptions never
take effect, and nothing arrives. Running the tick logger while this fetch was in flight
produced exactly that: a live logger, no error, and zero ticks. Do not run two tools against
the same account concurrently; use the demo account for anything that can tolerate demo
prices, and serialise the rest.

Run:  python -m scripts.fetch_universe --years 6
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from config.instruments import asset_class_of, extended_universe, universe


def _bars_stored(symbol: str, period: str) -> int:
    """Ground truth: how many bars are actually in the store for this symbol."""
    import sqlite3
    try:
        c = sqlite3.connect("data/market.db")
        n = c.execute("SELECT COUNT(*) FROM bars WHERE symbol=? AND period=?",
                      (symbol.upper(), period.upper())).fetchone()[0]
        c.close()
        return int(n)
    except Exception:
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch deep history for the research universe.")
    p.add_argument("--years", type=float, default=6.0)
    p.add_argument("--period", default="H1")
    p.add_argument("--classes", nargs="*", default=None,
                   help="limit to these asset classes (default: all)")
    p.add_argument("--extended", action="store_true",
                   help="include EXTENDED_UNIVERSE (research only)")
    p.add_argument("--skip-existing", action="store_true",
                   help="skip symbols that already have bars at this period")
    args = p.parse_args()

    pick = extended_universe if args.extended else universe
    symbols = pick(*(args.classes or ()))
    if args.skip_existing:
        symbols = [s for s in symbols if _bars_stored(s, args.period) == 0]
    print(f"fetching {args.years} years of {args.period} for {len(symbols)} instruments\n")
    ok, failed = [], []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ({asset_class_of(sym)})")
        r = subprocess.run([sys.executable, "-m", "market.bars", "--symbol", sym,
                            "--period", args.period, "--years", str(args.years)],
                           capture_output=True, text=True, timeout=900)
        # Verify the DATABASE, not the exit code or the log line. Three symbols reported
        # success and stored nothing when a concurrent process held the account session:
        # the fetch failed silently and the script believed its own stdout.
        stored = _bars_stored(sym, args.period)
        if r.returncode == 0 and stored > 0:
            print(f"      {stored:,} bars stored")
            ok.append(sym)
        else:
            # A symbol the account cannot reach is a finding, not a crash. Keep going.
            err = (r.stderr or r.stdout).strip().splitlines()
            print(f"      FAILED: {err[-1][:100] if err else 'no output'}")
            failed.append(sym)
        time.sleep(1.0)

    print(f"\ndone: {len(ok)} fetched, {len(failed)} failed")
    if failed:
        print(f"  not available on this account: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
