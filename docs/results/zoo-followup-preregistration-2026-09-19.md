# Zoo follow-up pre-registration: slow relative ML, 2026-09-19

Written after the zoo development results, before this follow-up runs. It is a search informed
by those results, so every candidate below is added to the honest N.

## What the zoo showed

* Nothing beats `long_risk_parity` (dev 0.50, itself DSR 0.016).
* The dev champion `gru_seq` (0.22) is mostly the long bias: correlation 0.80 with
  `long_risk_parity`, mean forecast 0.92, residual gross Sharpe 0.05.
* Pooled trees carry a RELATIVE signal before costs. With the per-date mean forecast removed,
  `xgb_shallow` gross 0.73, `extra_trees` 0.53, `mlp` 0.47, but turnover of 60 to 90 times a
  year makes all of them negative net.

## Hypothesis

The pooled ML relative signal is real but too fast. A slower version keeps enough of it to
survive costs. Falsified if every slowed variant stays at or below zero net on development.

## Candidates (6, all count in N)

For each of `xgb_shallow`, `extra_trees`, `ens_ml` (the zoo's cached out-of-sample forecasts):

1. Demean per date (remove the common long bias).
2. Smooth per instrument with an EWMA of span S, S in {10, 30}.
3. Rescale with prior years' out-of-sample magnitude only, cap at 2.

Names: `rel_{model}_s{S}`. Same costs, buffer, split and pass rule as the zoo.

## Holdout

The holdout remains unread. It is read once at the end of today's research programme for the
single best development candidate across the zoo, carry and this follow-up, plus `cash` and
`long_risk_parity`. That is a change in TIMING from the zoo pre-registration (which read it
after the zoo), made so one holdout read covers the whole day instead of several.
