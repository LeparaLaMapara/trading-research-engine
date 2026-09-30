# E09 DRAFT pre-registration: short Ethereum only when perpetual funding is high

**Status: DRAFT for the owner's review. Not registered, not run, no slot spent.** It becomes a
pre-registration only when it is moved to `docs/programme/`, added to `register.json` and
pushed, before any code that scores it exists. Written 30 September 2026. The funding data has
been downloaded but has NOT been compared with prices; nothing here is tuned.

## The idea in plain words

When crypto futures trade far above spot, small leveraged investors are piling into longs and
too little arbitrage money leans against them. The paper below finds that this predicts falling
prices. On this broker, a short Ethereum CFD pays no overnight financing (longs pay about 20% a
year), so the cost that killed every long crypto idea does not apply to a short one.

## Source (full text read, owner-supplied PDF)

Schmeling, Schrimpf and Todorov, "Crypto carry", BIS Working Paper 1087, March 2023 (published
in Management Science, doi:10.1287/mnsc.2024.05069). Quoted from the working paper:

* p. 3: "a positive carry predicts both a decline in the spot as well as in the futures price"
  and "These results indicate that a high carry predicts future crypto price crashes."
* p. 13: "The estimates for 1-months OKEx futures, for example, show that a one-dollar increase
  in the basis roughly predicts a six-dollars drop in the futures premium and five-dollars drop
  in the spot at expiration."
* p. 13, the limits: "Estimates for 1-month futures generally have lower degree of statistical
  significance than those for 3-month" and, over the longest data, "The estimates are only
  marginally significant for 3-month ETH".
* p. 6: the sample is "daily data from March 2019 to January 2022".

What the paper does not do: no trading strategy, no transaction costs, no out-of-sample test,
and carry is highly persistent (daily autoregression near one), which can overstate
significance in predictive regressions. This experiment supplies what it lacks.

## One difference from the paper, stated

The paper uses the dated-futures basis. This engine holds perpetual funding rates, which are
how a perpetual future's premium over spot is paid out, every eight hours. Funding is the
perpetual analogue of carry, not the same series. If funding does not behave like the basis,
this test fails for that reason, and the result says so.

## Data

* Funding: Binance ETHUSDT perpetual, every 8 hours, from `data/external/funding.parquet`
  (data_ext/fetch.py; the manifest SHA-256 is recorded in the result). BitMEX ETHUSD is
  reported as a robustness check only.
* Prices: the broker's ETHUSD daily bars (21:00 UTC close), `data/market.db`.
* Costs: round trip 12.9 bps (the spread measured by the live check, 12.21 bps median, plus
  0.7 bps commission). Short financing zero (broker `swapShort` 0.0). Doubled costs tested.

## The rule (fixed here)

At each completed daily bar close (21:00 UTC), using only funding paid at or before that time:

1. F = the mean of the last 21 funding rates (7 days), annualised (x 3 x 365).
2. High = F above the 80th percentile of F over the preceding 365 days (at least 180 days of
   history required; no lookahead).
3. If flat and High: short one unit at that close, held for exactly 30 days, with a
   protective stop at entry + 4 x (20-day standard deviation of daily returns) x price (the
   live risk layer requires a stop). Exit at the 30th close or the stop, whichever is first.
4. After an exit, the rule may re-enter at the next close if High still holds.
5. Otherwise flat. Never long.

One rule, one parameter set: 1 trial. N becomes 307.

## Samples

* **Deciding:** 1 February 2022 to 31 August 2026, entirely after the paper's sample ends.
* **Reported, not deciding:** November 2019 to January 2022 (the paper's own period), as a
  replication check.

## Pass criteria (all must hold on the deciding sample)

* **C1:** net return and net Sharpe (daily, 365 days a year) above zero.
* **C2:** average net return per episode above the 99th percentile of 10,000 random-timing
  nulls: the same number of 30-day short episodes, placed at random non-overlapping start days
  in the same window, same costs and stop (seeds 0 to 9,999). This separates "funding timed
  the shorts" from "Ethereum fell over the period".
* **C3:** at least 8 episodes. Fewer is INCONCLUSIVE: the slot is spent and nothing goes live.
* **C4:** net return above zero with costs doubled.
* **C5:** episode-level bootstrap (10,000 resamples, seed 0): fewer than 10% of resamples
  have a total net return at or below zero.
* **C6:** net return positive in both halves of the deciding sample, split at its middle day.

Reported, not deciding: deflated Sharpe at N = 307; always-short Ethereum over the same window;
the BitMEX version; the in-sample replication; the largest single episode's share of the total.

## What happens after

* PASS: the rule goes live short-only at 0.01 ETH within the signed limits. It is mostly flat,
  so most days the account holds nothing.
* FAIL or INCONCLUSIVE: written down; the slot is spent; nothing goes live.

## Expectation, written before running

Power is low. High-funding spells last weeks, so 4.6 years may hold only about 8 to 15
episodes, and C3 or C5 may fail for lack of evidence rather than for a wrong idea. Ethereum
fell for much of 2022, which is why C2 compares against random-timed shorts, not against zero.
My prior that this passes all six criteria is about one in four.
