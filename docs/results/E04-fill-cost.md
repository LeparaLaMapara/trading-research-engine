# E04 result: what a real fill costs. PASS

20 live EURUSD round trips at 0.01 lots, 22 September 2026, 18:32 to 18:56 UTC, after the
pre-registration was committed (d7b85e9). Authorised by the owner; the grant was signed for this
run only and revoked when it ended. Raw numbers: `E04-fill-cost.json`. Re-score with
`python -m scripts.e04_fill_cost`.

## Result

| criterion | needed | got | |
|---|---|---|---|
| C1 average slippage per fill | at most 0.1 pip worse than the quote | 0.013 pip BETTER | pass |
| C2 average cost per round trip | at most 1.25 x the modelled $0.07 | $0.066 | pass |

* 38 fills measured (20 entries, 18 exits; the exits of probes 1 and 2 had no reference quote,
  a bug fixed from probe 3 on). 26 filled exactly at the quote, 7 better, 5 worse. None was
  worse than 0.1 pip.
* No rejections. Every probe closed.
* Send to fill took 1.11 seconds on average (1.18 s to open, 1.04 s to close), matching the
  engine's earlier latency measurement.
* Total cost of the experiment: $1.31, most of it commission.

## What it means

For EURUSD at this size, in this hour, the backtests' assumption holds: a market order fills at
the quoted price, and the cost of a trade is the spread plus commission. No slippage needs to
be added to the cost model. That removes one of the two open methodological debts listed on
20 September.

## Limits

* One symbol, one size, one evening hour, outside the London and New York overlap. A larger
  order, a thinner market, or a news spike could slip. E03's crypto test is the most exposed to
  this, and XRPUSD fills were not measured here.
* The broker reports commission rounded to the cent ($0.03 a side, true about $0.035).

## Budget

2 of 10 spent (E01 FAIL, E04 PASS). E04 is a measurement: its pass is not a strategy and does
not bring a live trade closer by itself.
