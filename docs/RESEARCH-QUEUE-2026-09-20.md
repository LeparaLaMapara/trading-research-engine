# Research queue, 20 September 2026

Generated from the candidate sweep, the literature review and the data-quality audit. Priority
is `expected information gain x potential value / cost`, scored 1 to 5 on each and shown as a
product. The queue is the decision, not a wish list: anything below the line is not being
worked on, and the reason is stated.

## What the evidence now says

The candidate sweep classified all 20 candidates under one protocol:

| failure mode | count | meaning |
|---|---|---|
| EDGE_DESTROYED_BY_COSTS | 14 | the signal is real before friction and dies after it |
| NO_PREDICTIVE_EDGE | 4 | the signal is worthless before friction |
| NOT_DISTINGUISHABLE_FROM_LUCK | 2 | positive net, not separable from chance |
| EDGE_DESTROYED_BY_LATENCY | 0 | nothing we hold is latency-limited |

**This is the central finding of the week.** The pooled models carry gross Sharpe of 0.5 to
0.9 before friction. Costs of 0.4 to 1.1 take it away. Latency takes nothing measurable. So the
binding constraint is the cost of trading, not the quality of prediction and not our speed.

Two consequences follow, and they set the queue:

1. Work that reduces cost per unit of signal is worth more than work that improves prediction.
2. The 4 NO_PREDICTIVE_EDGE candidates should stop consuming compute entirely.

## The queue

| # | experiment | information | value | cost | priority | status |
|---|---|---|---|---|---|---|
| 1 | **H5 null:** nothing from top-of-book prices alone beats the cost floor at 1 to 60 s | 5 | 3 | 1 | **15.0** | ready, data in hand |
| 2 | **H1 lead-lag:** Binance leads VALR at a tradeable horizon | 4 | 5 | 2 | **10.0** | blocked on collection, start now |
| 3 | **Venue cost re-scoring:** re-run the sweep against VALR perp and CME micro cost tables | 3 | 5 | 1 | **15.0** | ready, no new data |
| 4 | **Data quarantine:** enforce the audit's exclusions before any further zoo run | 5 | 2 | 1 | **10.0** | ready |
| 5 | **H4 book imbalance** on the broker's depth feed, now that depth is recording | 3 | 3 | 2 | **4.5** | collecting |
| 6 | **Sub-hour decay band:** M1 bars plus the tick recorder, to price delays between 1 s and 1 h | 3 | 2 | 2 | **3.0** | partly collecting |
| 7 | **H3 quarter-hour execution timing** on our own fills | 2 | 1 | 1 | **2.0** | needs 200 live orders, we have 1 |

Ranked by priority, the order of work is 1 and 3 together (both free and immediate), then 2
(starts the clock on data that only accumulates in real time), then 4, then 5.

## Why 3 is the highest-value cheap experiment

The sweep says costs are the binding constraint. We already hold the signals; re-pricing them
at a different venue's costs is a spreadsheet operation, not new research. If the pooled ML
signal survives at VALR perpetual costs (0.14% round trip, funding instead of a fixed holding
fee) or at exchange futures costs (no holding fee at all), then the whole programme changes
target. If it does not survive even there, the conclusion hardens: our signals are not merely
expensive, they are weak, and prediction work must resume from a different data source.

## What is being stopped

* `ewmac`, `ens_rules`, `xs_momentum`, `short_reversal`: NO_PREDICTIVE_EDGE, gross Sharpe at or
  below zero over 64 instruments and 8 years, plus negative in every era over 23 years in the
  long-history test. They are retired from the search space, recorded in the lessons table so
  the council cannot re-propose them as novel.
* Any further hardware or hosting investigation. Latency cost measured at our operating delay
  is zero for everything we hold, and the perfect-foresight ceiling literature says the money
  available shrinks as the horizon shortens.
* Deep-learning capacity increases. The GRU's apparent edge was 80% long-bias, and the sweep
  puts its net inside the luck band.

## Open methodological debts

* Slippage is still **not separately measured**. We have one live fill. Until there are
  enough, `slippage` prints as "not measured" rather than zero, and EDGE_DESTROYED_BY_SLIPPAGE
  can never currently be diagnosed.
* Latency cost at our true operating delay of about 2 seconds is **unmeasurable with hourly
  data**. It is bounded, not known.
* The data quarantine from the audit is written but **not yet enforced in code**.
