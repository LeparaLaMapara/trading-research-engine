# E12 pre-registration: short the dollar on Fed decision days

**Status: registered 31 October 2026, committed and pushed before any scoring code exists.**
Programme P2, second slot. Decided by the research lead under the owner's 2026-10-31 goal.
The Fed meeting dates and hourly prices have been downloaded; no return on any FOMC day has
been computed.

## The idea in plain words

Eight times a year the US Federal Reserve announces interest rates. Banks that carry currency
positions into that announcement bear the risk of a surprise, and get paid for it: on decision
days the dollar has tended to fall against other currencies, more so for high-interest
currencies. The trade: sell the dollar against the other majors from 4pm New York the day
before a decision to 4pm New York on the day, then go flat.

## Source (full text read)

Mueller, Tahbaz-Salehi and Vedolin, "Exchange Rates and Monetary Policy Uncertainty", Journal
of Finance 72(3), 2017 (LSE accepted version). Quoted:

* "a trading strategy that is short the U.S. dollar ... earns significant excess returns on
  days with scheduled FOMC announcements".
* p. 16, the dollar portfolio: "a large and statistically significant return on announcement
  days (10.77bps, with a t-statistic of 2.27)", against an insignificant return on other days.
* Data: "tick-by-tick high-frequency data that runs from January 1, 1994 to December 31, 2013";
  daily returns "sampling the data at 4pm Eastern Time (ET)".
* Section E.2: net of bid-ask spreads the effect is "qualitatively the same".

## Differences from the paper, stated

1. Spot returns only. The paper's excess return adds the interest differential through the
   forward discount; here the broker's actual overnight financing for the one night held
   (17:00 ET on the day before) is charged instead, from `data/swaps.json`.
2. Seven currencies the broker quotes against the dollar (EUR, GBP, JPY, CHF, AUD, NZD, CAD),
   equal weight, no interest-rate sorting. The live limits allow two positions; if this
   passes, choosing which two is a separate, counted experiment.

## Data

* FOMC dates: scheduled statement days 2014 to 2026 from the Federal Reserve's own pages
  (`news/fomc.py` -> `data/fomc_dates.json`; 102 dates, March 2020 cancelled, unscheduled
  meetings and notation votes excluded).
* Dukascopy hourly bid AND ask bars, 2014-01-01 to 2026-09-30 (`T:\making-money\features\
  intraday\h1`; SHA-256s in the result). 16:00 ET is the open of the hourly bar at 20:00 UTC
  (US summer) or 21:00 UTC (winter).
* Fill at that bar's open: buy at the ask, sell at the bid. Commission 0.35 bps per side.
  Financing: one night at the broker swap for the side held (`data/swaps.json`).
* An event is dropped if any fill bar is missing or crossed; dropped events are reported.

## The rule (fixed here)

For each scheduled FOMC statement day D in the sample, with D-1 the previous weekday:

1. At 16:00 ET on D-1, sell the dollar against each of the seven currencies, equal notional:
   BUY EURUSD, GBPUSD, AUDUSD, NZDUSD; SELL USDJPY, USDCHF, USDCAD.
2. At 16:00 ET on D, close all seven.
3. Event return = the equal-weight average of the seven net returns.

## Deciding sample

**2014-01-01 to 2026-09-30** (all after the paper's 2013 end): about 101 events.

## Pass criteria (all four, on the event returns)

1. Mean net event return > 0 with t >= 2.0.
2. Mean above the 95th percentile of 2,000 nulls, each drawing the same number of random
   non-FOMC weekdays with the same weekday mix (mostly Wednesdays), same rule and costs.
3. Mean > 0 with spread, commission and financing all multiplied by 1.5.
4. Mean net event return positive in both halves (2014-2019 and 2020-2026).

The deflated Sharpe at the running N is reported. A PASS makes the rule a forward-test
candidate only when deflated Sharpe >= 0.5; a live rule needs 0.95 at N.

## Trials counted

8: the seven single-currency versions (diagnostics) plus the equal-weight book (decides).

## What would make me wrong

Eight events a year is little data: about 101 events over twelve years. A real 10 bps effect
with event volatility around 50 bps gives t near 2 only if it held at full strength, so a
weakened effect will most likely come back UNDECIDED-looking and fail criterion 1. That would
be an honest "not proven", not proof of absence.
