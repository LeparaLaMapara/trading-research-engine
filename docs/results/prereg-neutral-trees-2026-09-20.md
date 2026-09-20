# Pre-registration: market-neutral tree signal at futures-like costs

Written and committed BEFORE the holdout is read for this hypothesis.

## Claim

A pooled gradient-boosted tree, trained across 64 instruments to predict the 5-day
vol-normalised return, contains information about WHICH instruments outperform others, and
that information survives a cost structure without a fixed holding fee.

Formally: with the cross-sectional mean forecast removed each day (so no net market exposure)
and costs set to a futures-like 1.3 bps round trip with no holding fee, the strategy earns a
positive net Sharpe out of sample, above what the same pipeline produces when instrument labels
are permuted.

## What is already known, and why the holdout is needed

* Development window 2017-01-01 to 2024-09-15: market-neutral net Sharpe **+0.629**, above all
  150 label permutations (null mean -0.409, sd 0.350, max +0.353).
* The same signal at OUR broker's costs is **-0.32**: the claim is explicitly about the cost
  structure, not about our current venue.
* The candidate was selected AFTER seeing development results. That is selection bias, and no
  amount of within-development testing removes it. Only untouched data can.

## The test, fixed now

Window: 2024-09-16 to 2026-09-15, never used to select anything for this hypothesis.
Instruments: the same 64. Forecasts: the cached walk-forward out-of-sample predictions, which
for this window were produced by a model trained only on data before it.
Costs: 1.3 bps round trip, no holding fee, identical to development.
Position construction: identical, including the 0.25 buffer and per-instrument vol scaling.

## Pass criteria, ALL required

1. Net Sharpe on the holdout > 0.
2. Above the 95th percentile of 150 instrument-label permutations run on the same window.
3. Positive in both holdout years taken separately.

## What each outcome means

* All three pass: the signal is a candidate worth paper trading at a venue with this cost
  structure. It is NOT a licence to trade at our broker, where the same signal is negative.
* Any fail: the development result is attributed to selection, recorded as such, and the
  tree family is retired from cross-sectional work.

## Prior

The literature and our own record argue for caution: nothing in this project has ever passed
an out-of-sample test. Stated probability of all three criteria passing: about 30%.
