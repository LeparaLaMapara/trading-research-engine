# E06 pre-registration: does breadth add? E05's rule across eight coins, combined

Written and committed on 23 September 2026, BEFORE the test is run. Experiment 6 of 10.

## Why

The owner's idea (23 September): many small edges across many instruments, added together,
become a large one. That is the "fundamental law of active management": the combined strength
of independent edges grows roughly with the square root of how many there are. It holds only if
each edge survives its own costs AND the edges are not all the same bet.

E05 (Ethereum 20-day trend) passed on history. At the account's size (about R1,530), crypto is
where breadth is affordable: BTC's minimum is too big, but LTCUSD and BCHUSD trade at 0.01 coin
and ETHUSD at 0.01. Coins move together, so the question is not "does the rule work on other
coins" but **"does trading it on several coins make the combined result better than Ethereum
alone?"**

## The rule

E05's rule, unchanged (`lab/eth_trend.simulate`: 20-day sign, entry at the next open, 2-sigma
stop, 1.5R target, stop first when both are touched, 20% a year on longs, shorts free), applied
separately to each of the eight coins with daily bars: ADAUSD, BCHUSD, BTCUSD, DOTUSD, ETHUSD,
LTCUSD, SOLUSD, XRPUSD.

Costs per coin: today's measured spread as a fraction of today's price where the engine has
measured it, otherwise the pessimistic crypto class default (15 bps), plus 0.35 bps commission
per side.

## Combining (the new layer)

Each day, each coin's rule return is weighted by the inverse of that coin's price-return
volatility over the previous 60 days (prior days only), and the weights of the coins trading
that day are normalised to sum to 1. A coin joins once it has 60 days of history. This is an
equal-risk portfolio: a wild coin gets a smaller slice than a calm one.

Sample: 1 January 2018 to the last bar stored when the pre-registration was written
(18 September 2026).

## Pass criteria (all four required)

* **C1**: the combined portfolio's net Sharpe is above the 95th percentile of 200 random-sign
  nulls (seeds 0 to 199; random sign per coin-day through the same mechanics and weights).
* **C2 (does breadth add?)**: the combined net Sharpe is above ETHUSD alone's net Sharpe over
  the same dates, with the same code.
* **C3**: combined net return positive in at least 6 of the 8 calendar years 2018 to 2025.
* **C4**: combined net Sharpe above 0 with costs doubled.

Reported, not deciding: each coin's own net Sharpe; the average correlation between the coins'
rule returns; the effective number of independent bets (from the correlation matrix's
eigenvalues); deflated Sharpe at N = 299.

## What each outcome means

* All pass: breadth adds, and the engine should trade the rule across the coins the account can
  afford. That needs more than 2 open positions, so the signed position limit would have to be
  raised: an owner decision, asked for only if E06 passes.
* C2 fails: the coins are effectively one bet, and breadth must come from different kinds of
  markets, not more coins. That redirects the remaining four experiments.

## Counting

One trial: one fixed rule and one fixed combining method.
