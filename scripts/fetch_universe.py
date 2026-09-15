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

from config.instruments import asset_class_of, universe


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch deep history for the research universe.")
    p.add_argument("--years", type=float, default=6.0)
    p.add_argument("--period", default="H1")
    p.add_argument("--classes", nargs="*", default=None,
                   help="limit to these asset classes (default: all)")
    args = p.parse_args()

    symbols = universe(*(args.classes or ()))
    print(f"fetching {args.years} years of {args.period} for {len(symbols)} instruments\n")
    ok, failed = [], []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ({asset_class_of(sym)})")
        r = subprocess.run([sys.executable, "-m", "market.bars", "--symbol", sym,
                            "--period", args.period, "--years", str(args.years)],
                           capture_output=True, text=True, timeout=900)
        tail = [ln for ln in r.stdout.splitlines() if "total" in ln or "stored" in ln]
        if r.returncode == 0 and tail:
            print(f"      {tail[-1]}")
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
