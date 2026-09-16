"""How many instruments should this engine actually trade, and which ones?

Answers it from the bars on disk rather than from a hunch about what feels diversified.
Prints Carver's table rebuilt on THIS universe's measured correlations, so the comparison
between the published reference (37 futures markets, average correlation 0.233) and the
basket actually available here is explicit.

    python -m scripts.breadth                      # whole research universe, H1
    python -m scripts.breadth --period H4 --top 8
    python -m scripts.breadth --classes fx_major metal crypto

Reports only. It changes nothing and trades nothing.
"""
from __future__ import annotations

import argparse
import sys

from backtest.run import load_bars
from config.instruments import asset_class_of, universe
from research.diversify import (CARVER_RHO, CARVER_SINGLE_SHARPE, PRACTICAL_BREADTH,
                                breadth_report, correlation_matrix, out_of_sample_idm,
                                portfolio_sharpe, returns_frame)

MIN_COMMON_BARS = 200


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):            # pragma: no cover
        pass

    ap = argparse.ArgumentParser(description="Measured diversification report.")
    ap.add_argument("--period", default="H1")
    ap.add_argument("--classes", nargs="*", default=[],
                    help="asset classes to include (default: all)")
    ap.add_argument("--top", type=int, default=PRACTICAL_BREADTH,
                    help="size of the recommended basket")
    ap.add_argument("--single-sharpe", type=float, default=CARVER_SINGLE_SHARPE,
                    help="what one stream is worth alone; defaults to Carver's 0.35 because "
                         "this engine has not measured a positive one of its own")
    args = ap.parse_args()

    symbols = universe(*args.classes)
    bars, missing = {}, []
    for s in symbols:
        df = load_bars(s, args.period)
        if df.empty:
            missing.append(s)
        else:
            bars[s] = df
    if missing:
        print(f"no {args.period} bars for {len(missing)}: {', '.join(missing)}")
    if len(bars) < 2:
        print("need at least two instruments with bars. Fetch first: "
              "python -m scripts.fetch_universe")
        return 1

    rets = returns_frame(bars)
    if rets.empty or len(rets) < MIN_COMMON_BARS:
        print(f"only {len(rets)} timestamps common to all {len(bars)} instruments, need "
              f"{MIN_COMMON_BARS}. Correlations on less than that are noise.\n"
              f"Try fewer classes, or a coarser --period.")
        return 1

    corr = correlation_matrix(rets)
    rep = breadth_report(corr, single_sharpe=args.single_sharpe)

    print(f"\n{len(corr)} instruments, {len(rets)} timestamps in common, {args.period}")
    print(f"measured average correlation  rho = {rep.rho:.3f}    "
          f"(Carver's 37 futures markets: {CARVER_RHO})")
    if rep.rho > CARVER_RHO:
        print("  -> this universe is MORE correlated than Carver's, so every count below "
              "buys less\n     than his published table promises. That is the honest number.")

    print(f"\nrecommended basket, least-correlated first (top {args.top}):")
    for row in rep.table[:args.top]:
        cls = asset_class_of(row["added"]) or "?"
        mark = "  <- most of the benefit is here" if row["n"] == PRACTICAL_BREADTH else ""
        print(f"  {row['n']:>2}. {row['added']:<8} {cls:<10} rho={row['rho']:+.3f}  "
              f"IDM={row['idm']:.2f}  Sharpe={row['sharpe']:.3f}{mark}")

    if len(rep.table) > args.top:
        last = rep.table[-1]
        gain = last["sharpe"] - rep.table[min(args.top, len(rep.table)) - 1]["sharpe"]
        if gain >= 0:
            print(f"\n  all {last['n']} instruments would give Sharpe "
                  f"{last['sharpe']:.3f}, only {gain:+.3f} more than the top {args.top}.")
        else:
            # Equal weight across a correlated tail LOWERS the multiplier. Adding
            # instruments is not automatically diversifying, and reporting a dilution as
            # though it were a gain would be the same mistake as assuming eight FX majors
            # are eight streams.
            print(f"\n  all {last['n']} instruments would give Sharpe "
                  f"{last['sharpe']:.3f}, which is {abs(gain):.3f} LESS than the top "
                  f"{args.top}. Equal weight across the correlated tail DILUTES the\n  "
                  f"basket: more instruments is not automatically more breadth.")

    # The table above was BUILT on these correlations, so it is the in-sample view and it
    # flatters itself. Check it the way this project checks everything else: choose on the
    # first half, measure on the second.
    oos = out_of_sample_idm(rets, args.top)
    if oos["evaluable"]:
        ref = oos["independent_reference"]
        print(f"\nout-of-sample check ({oos['n_train']} train / {oos['n_test']} test bars):")
        print(f"  chosen on train, IDM in-sample {oos['in_sample_idm']:.2f}  ->  "
              f"out-of-sample {oos['out_of_sample_idm']:.2f}   "
              f"(selection bias {oos['selection_bias']:+.2f})")
        print(f"  perfectly independent streams: sqrt({args.top}) = {ref:.2f} in theory, "
              f"{oos['noise_floor_idm']:.2f} on {oos['n_test']} bars")
        print(f"  basket against that noise floor: {oos['idm_vs_floor']:.2f}x   "
              f"(1.00 = no better than independence)")
        if oos["in_sample_idm"] > ref:
            print("  IN-SAMPLE IDM IS ABOVE THE INDEPENDENT CASE. That is impossible for "
                  "real\n  correlations and is the signature of choosing on estimation "
                  "noise. Believe the\n  out-of-sample number, not the table above.")
        print(f"  honest Sharpe multiple: {args.single_sharpe:.2f} -> "
              f"{args.single_sharpe * oos['out_of_sample_idm']:.3f}")
    else:
        print(f"\nout-of-sample check skipped: {oos['why_not']}")

    single = portfolio_sharpe(args.single_sharpe, corr.iloc[:1, :1])
    best = rep.table[min(args.top, len(rep.table)) - 1]["sharpe"]
    print(f"\n  one instrument {single:.3f}  ->  {args.top} instruments {best:.3f}   "
          f"({best / single:.2f}x)")
    print("\nThis multiplies whatever edge a single stream has. It does not create one:\n"
          f"  {args.single_sharpe} x {best / single:.2f} is only worth having because of the "
          f"{args.single_sharpe}, and\n  this engine has not yet measured a positive Sharpe "
          "it believes. Breadth first is still\n  right: it is the one improvement that "
          "needs no new signal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
