# Model zoo pre-registration, 2026-09-19

Written and committed BEFORE any zoo model is run. Anything below that changes after the first
result must be recorded as a change, with the reason, in the results file.

## Question

Across a 64 instrument daily universe, does any forecasting method, from simple rules to pooled
machine learning, earn a portfolio level Sharpe after honest costs that survives the
multiple testing bar?

Secondary questions: does pooling across instruments beat per instrument and per class models
(mandate section 15)? Does complexity beat the simplest rule after costs (section 5)?

## Prior belief, stated before looking

Trend following on a diversified futures-like universe has a long published record (Moskowitz,
Ooi and Pedersen 2012; Hurst, Ooi and Pedersen 2017; Carver). Our own per instrument sweep
found nothing beyond chance. Prior: a diversified trend portfolio has a real but small edge
(portfolio Sharpe 0.3 to 0.6 before our costs); ML on daily OHLC alone adds little or nothing
over it. Probability something passes DSR 0.95 today: about 20%.

## Data

* D1 bars from IC Markets via cTrader, `data/market.db`, 64 instruments (core 24 plus 40
  extended), up to 12 years, last bar 2026-09-15.
* Daily date = UTC timestamp plus 3 hours, floored to the date (broker rolls at 21:00 UTC).
* Instruments enter the panel only after 300 bars of their own history (warm up).

## Split

* **Holdout, locked:** every date on or after **2024-09-16** (two years). Touched ONCE, only
  for the dev champion and the pre-declared comparison set: `cash`, `long_risk_parity`,
  the best simple rule. Nothing is chosen using the holdout.
* **Development:** expanding window walk forward by calendar year. Train on all dates before
  1 January of year Y minus a 10 day embargo, predict year Y, for Y = 2017 to 2024 (2024 ends
  at 2024-09-15). Rules with no fitted parameters are simply evaluated over the same dates.

## Costs, applied to every model identically

* Spread plus commission per unit of notional traded, from `backtest.run.measured_cost`
  (measured telemetry where held, pessimistic basis point defaults where not).
* Financing on held notional, charged BOTH directions (conservative, ignores carry earned):
  FX 1.0%, index 3.0%, metal 2.5%, energy 3.0%, crypto 15% per year.
* No trade buffer: a held position is only changed when the new target differs by more than
  0.25 forecast units. Same buffer for every model.

## Position construction, identical for every model

Forecast f (dimensionless, scaled on TRAINING data so mean |f| = 1, capped at plus or minus 2).
Position in notional = f / sigma, sigma = EWMA daily vol (span 36) known at the close of the
signal day. Portfolio return each day = average across available instruments. Scale of the
portfolio does not affect Sharpe; returns are reported at 10% annual vol for readability.

## Candidates (each counts towards N)

Baselines: cash, long_risk_parity, random_sign (seed 7).
Rules: ewmac (Carver 8/32 to 64/256 equal blend), breakout (20/40/80/160), tsmom_12m
(sign of 250 day return), xs_momentum (rank of 120 day return within class),
short_reversal (minus 5 day return).
Pooled linear: ridge_pooled, logistic_pooled.
Pooling test: ridge_per_class, ridge_per_instrument.
Trees: xgb_shallow (depth 3), xgb_deep (depth 6), extra_trees, random_forest.
Neural: mlp (torch), gru_seq (60 day normalised return sequences, torch).
Ensembles: ens_rules, ens_ml, ens_all (equal weight of forecasts).

No hyperparameter search. Each has one fixed canonical configuration.

## Decision rule

* Champion = highest development portfolio Sharpe (net). One champion.
* PASS requires ALL of: deflated Sharpe >= 0.95 on the development series against
  N = every candidate this engine has ever scored (210 before today plus every zoo row);
  holdout net Sharpe > 0; positive development Sharpe in at least 5 of 8 years.
* A PASS means "paper trade it and keep measuring", never "trade it live". Live money needs
  the owner's signed grant.

## Verdict vocabulary

FALSIFIED, UNDERPOWERED, UNEVALUABLE, TOO_EXPENSIVE, IMPLEMENTATION_FAILURE, DATA_FAILURE,
SUPERSEDED, UNRESOLVED, SURVIVED. Carry (interest differential) is not tested: no point in
time rate history is held. That is DATA_FAILURE, not falsified.
