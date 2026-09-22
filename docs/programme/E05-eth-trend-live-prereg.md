# E05 pre-registration: Ethereum 20-day trend, tested on history AND traded live

Written and committed on 23 September 2026, BEFORE the historical test is run and before any
order. Experiment 5 of 10.

## Why this one, and why it trades live whatever the test says

On 22 to 23 September the owner said, in his words: "I don't want it to ask me anymore ... the
objective is to get better, learn as much as you can and start beating the market," and that
losses are acceptable. So from 23 September the engine trades the live account on its own,
inside the signed risk limits (6% risk per trade, 2 positions, stop permanently at $20 equity).

At about $28 of equity, the only instrument the limits allow is **ETHUSD at 0.01**: currencies,
gold, silver, oil and indices all need more margin than 50% of equity, and BTCUSD's minimum
size needs about $16 of margin. So the live rule must be an Ethereum rule.

The rule is chosen from the literature, not from this data: Liu and Tsyvinski (2021), "Risks
and Returns of Cryptocurrency", Review of Financial Studies 34, doi:10.1093/rfs/hhaa113
(resolved via Crossref 23 September 2026), find time-series momentum in cryptocurrencies at
horizons of one to four weeks.

## The rule

* Once a day, after 00:00 UTC, on ETHUSD daily bars: the signal is the sign of the return over
  the last 20 completed days (close of yesterday over close 20 days before).
* Positive: hold one long position. Negative: hold one short position. The broker charges longs
  about 20% a year and shorts nothing (`data/swaps.json`).
* Each position opens at market with a broker-side stop at 2 daily sigmas (EWMA, span 36) and a
  target at 1.5 times the stop, sized by the risk officer (at this equity, 0.01 or nothing).
* If the stop or target closes it, the engine re-enters at the next daily decision if the signal
  still points the same way. If the signal flips, the engine closes its position and opens the
  other way.
* The engine only manages positions it opened (label `engine-E05`). The ETHUSD trade opened by
  hand on 20 September is left alone.

## Part A: the historical test (decides whether the rule has any evidence)

ETHUSD daily bars from the first stored bar (24 September 2017) to 18 September 2026, simulated
exactly as above: entry at the next day's open, stop and target checked against each day's high
and low (if both are touched the same day, the stop is assumed first), 20% a year financing on
longs, one measured spread plus two sides of commission per round trip.

Pass criteria, all four required:

* **C1**: net annualised Sharpe above 0.
* **C2**: net Sharpe above the 95th percentile of 200 random-sign nulls (seeds 0 to 199) with
  the same stop, target and cost mechanics.
* **C3**: net positive in at least 5 of the 8 calendar years 2018 to 2025.
* **C4**: net Sharpe above 0 with spread and commission doubled.

## Part B: the live record (what the owner asked for)

The engine trades the rule live from 23 September 2026 regardless of Part A, and every trade is
logged and published. After 20 live round trips, the live results are compared with Part A's
per-trade distribution: if live average P&L per trade is below Part A's 5th percentile, the
execution is costing more than the model says and that becomes the next experiment.

## What each outcome means

* Part A passes: a rule with evidence is trading. The E05 slot is a strategy PASS.
* Part A fails: the engine still trades it, because the owner chose live learning over waiting,
  but the dashboard says plainly that the rule it is trading has no historical edge.

## What replaces the rule

Any later strategy experiment that passes and that this account can afford replaces E05 as the
live rule automatically. That is the learning loop.

## Counting

One trial (one rule, one symbol). N = 298 (295 documented by 19 September, plus E01, E02, E05).
