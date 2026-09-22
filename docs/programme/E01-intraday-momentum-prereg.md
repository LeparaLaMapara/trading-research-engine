# E01 pre-registration: intraday momentum, flat before the overnight rollover

Written and committed on 22 September 2026, BEFORE the test is run. Experiment 1 of 10 in the
programme (`docs/programme/README.md`).

## Why this experiment

The largest cost at this broker is the overnight financing charge, taken at the 21:00 UTC
rollover (`swapTime` 1260 minutes in `data/swaps.json`, for every symbol). A position that is
closed before the rollover pays none of it. The engine measured its own order path at about one
second, so a strategy that holds for hours is well inside what it can execute. This experiment
asks whether a published intraday effect survives this broker's measured spreads when the
financing charge is removed by construction.

## Prior evidence (both resolved via Crossref on 22 September 2026)

* Gao, Han, Li and Zhou (2018), "Market intraday momentum", Journal of Financial Economics 129,
  doi:10.1016/j.jfineco.2018.05.009. The first half hour's return predicts the last half hour's
  return on the S&P 500 ETF.
* Elaut, Frömmel and Lampaert (2018), "Intraday momentum in FX markets: Disentangling informed
  trading from liquidity provision", Journal of Financial Markets 37,
  doi:10.1016/j.finmar.2016.09.002. The same effect in an FX market.

Both describe a return early in the session predicting the return late in it. The adaptation
below is to hourly bars and to this broker's rollover, and it is stated in full so it cannot
drift.

## The rule (no fitted parameters)

All times UTC. Bars are the hourly bars in `data/market.db`, stamped at their open.

1. **Morning return** for day d: from the open of the 23:00 bar on day d-1 to the open of the
   12:00 bar on day d.
2. **Signal**: the sign of the morning return (+1, -1, or 0 if exactly zero).
3. **Position**: the signal, held from the open of the 12:00 bar to the open of the 20:00 bar on
   day d. Eight hours. Flat at every other time, so never held across the rollover.
4. **Sizing**: each instrument is weighted by the inverse of the standard deviation of its own
   12:00 to 20:00 return over the previous 60 trading days (prior days only). An instrument
   needs 20 prior days before it trades. The day's portfolio return is the average across the
   instruments that traded that day.
5. A day is skipped for an instrument if any of the three bars (23:00 on d-1, 12:00 and 20:00
   on d) is missing.

The hours were chosen from the literature (early session predicts late session) and from the
rollover constraint (be flat before 21:00). They were not chosen by looking at this data.

## Data

* Every symbol with hourly bars in `data/market.db` (24 on 22 September: FX majors and crosses,
  metals, energy, indices, crypto), from the first stored bar (17 September 2020) to the last
  stored bar when the test runs.
* Disclosure: these hourly bars were used before by other hypotheses (moving-average trend,
  mean reversion and similar on EURUSD, USDJPY, XAUUSD). No intraday session return of the kind
  above has been computed on them.
* No dev/holdout split, because nothing is fitted: the whole sample is out of sample for a rule
  fixed in advance.

## Costs

* **Spread**: one full measured spread per round trip, from `backtest.run.measured_cost` (local
  telemetry, or the committed `data/spread_summary.json`, or the pessimistic class default where
  a symbol was never measured). Converted to a return at the entry price.
* **Commission**: 0.35 bps per side, two sides per round trip.
* **Financing**: zero, because the position is flat at the rollover. The test ASSERTS this: it
  fails if any position is open in a bar that starts at 20:00, 21:00 or 22:00 UTC.

## Pass criteria (all four required)

* **C1**: net annualised Sharpe of the portfolio over the whole sample is above 0.
* **C2**: net Sharpe is above the 95th percentile of a null: 200 draws (seeds 0 to 199) with a
  random sign per instrument-day in place of the signal, the same schedule, weights and costs.
  This null has the same turnover as the real rule, because the rule trades every day.
* **C3**: net return is positive in at least 4 of the 6 calendar years 2021 to 2026, AND over the
  last 12 months of the sample.
* **C4**: net Sharpe is still above 0 with spread and commission doubled. The exit at 20:00 UTC
  sits an hour before the rollover, where spreads widen and the recorder has few observations.

Reported but not deciding: gross Sharpe, Sharpe by asset class, the number of instrument-days,
and the deflated Sharpe at N = 296 (the 295 candidates documented by 19 September, plus this one).

## What each outcome means

* **All four pass**: E01 becomes a candidate for demo paper trading for three months. Not a live
  trade: that still needs the deflated Sharpe bar of 0.95 and the owner's signed grant.
* **Any fails**: E01 is recorded as FAIL in `register.json`, with the failing criteria, and the
  finding goes into the results. It counts against the budget of 10 either way.

## Counting

One trial. One fixed rule, no variants.
