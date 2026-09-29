# What the reading room must know about this engine

Every paper is read against these facts. They are measured or decided, not hoped. Keep this
file short and true; when a fact changes, change it here and the next weekly read uses it.
The register summaries and the research queue are added to this automatically.

## The account

* One live CFD account at IC Markets via the cTrader Open API, about 85 US dollars.
* Minimum size 0.01 lots. At this size only about 9 instruments fit the risk and margin limits:
  ETHUSD, ADAUSD, BCHUSD, LTCUSD, AUDCAD, AUDNZD, EURCAD, EURGBP, USDSGD. Most FX majors,
  gold, indices and BTC need more margin than the account can give.
* Signed limits: 6% risk per trade, at most 2 positions, 40% drawdown or a 20 dollar floor
  halts everything permanently.
* Live rules: none open new trades. Audit A01 (30 September 2026) demoted both: the Ethereum
  20-day trend (E07) earned all its edge in 2018 to 2022 and nothing since; the same rule on
  USDSGD (E08) cannot be told from zero (28% of bootstrap resamples at or below zero). Their
  last positions close on the rule's own exit. Any new rule must survive the same audit.

## What trading costs here (measured)

* Spread: EURUSD about 0.1 pip, EURGBP about 0.3, gold about 9 pips at the median hour,
  ETHUSD about 3 dollars per ETH. Spreads widen about tenfold at the 21:00 UTC rollover.
* Real fills (E04, 38 live fills on EURUSD): no slippage on average, 1.1 s from send to fill.
* Order round trip 369 ms minimum, 949 ms median, 3.5 s at the 99th percentile. No colocation.
* The biggest cost for anything held overnight is the broker's financing (swap). For crypto
  CFDs it is large.
* Broker D1 bars open and close at 21:00 UTC.

## What the evidence says so far

* Of 20 candidate strategies classified on 20 September 2026: 14 had a real edge before costs
  that costs removed, 4 had no edge at all, 2 were indistinguishable from luck, 0 were limited
  by speed. **The binding constraint is the cost of trading, not prediction and not latency.**
* Intraday momentum failed (E01, E02). Order-book imbalance on XRP failed after the spread (E03).
* Broker depth for BTC, ETH and SOL is a synthetic symmetric ladder: imbalance was exactly zero
  in 23,565 snapshots. Order-book research needs a real exchange feed.
* Trend following works on Ethereum (net Sharpe 0.80 over nine years) but not on most currency
  crosses (3 of 5 lose before costs). Breadth only helps with components that each have edge.
* Every rule tried is counted. N is 306 (it never resets across programmes), so a new result needs a deflated Sharpe that
  survives that count.

## Data

* Held: broker bars for 64 instruments (D1 back to 2014 or later for many), top-of-book ticks,
  XRP depth for 120 hours, live fills.
* Held since 30 September 2026 (data_ext/fetch.py, refreshed weekly on Databricks): FRED
  policy and 3-month interbank rates for USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF (no SGD rate);
  CFTC positioning for AUD, CAD, GBP, EUR, EURGBP, JPY, NZD, CHF, gold, ETH, BTC (weekly, most
  from 2000); perpetual funding for ETH and BTC (Binance from 2019, BitMEX ETH from 2018, OKX).
* Free to add later: real exchange order books (public, no account), economic calendars, MAS
  rates for SGD.
* Compute: research runs on Databricks (4 CPUs, 16 GB); the engine PC only trades and records.
* Not available: tick-level trade prints for FX, colocation, institutional flow data.

## How a test is run

* Pre-registered before the result exists, one hypothesis per slot, 10 slots per programme,
  2 left in programme P1. Audits re-test live rules and can only demote.
* Pass criteria include beating a random-sign null at the 99th percentile with the same costs,
  surviving doubled costs, and most years positive.
