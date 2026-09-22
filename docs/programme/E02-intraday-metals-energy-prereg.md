# E02 pre-registration: intraday momentum on metals and energy, on data E01 never saw

Written and committed on 22 September 2026, BEFORE the test is run and before the bars for
this period were fetched for any symbol except XAUUSD (fetched only to check the history
exists; nothing was computed on it). Experiment 2 of 10.

## Where the idea came from, and why this is still a fair test

E01 (FAIL) showed metals at +0.24 and energy at +0.04 net Sharpe. Those were subgroups picked
after seeing the data, so E01 recorded them as not a finding. A fair test needs data that did
not produce the idea. The broker serves hourly bars back to September 2014; E01 used only bars
from 17 September 2020 on. So E02 runs the identical rule on **metals and energy only, on bars
strictly before 17 September 2020**. No E01 day is in this sample.

## The rule

Identical to E01 (`docs/programme/E01-intraday-momentum-prereg.md`, code `lab/intraday.py`):
sign of the 23:00 to 12:00 UTC return, held 12:00 to 20:00 UTC, flat before the rollover,
inverse-volatility weights from the previous 60 days, 20 days of history before trading.

## Data

* Instruments: XAUUSD, XAGUSD, XAUEUR (metals); XTIUSD, XBRUSD (energy). Any that the broker
  cannot serve before 2020 are dropped and listed in the result.
* Sample: from the first stored hourly bar to 16 September 2020 inclusive.

## Costs

As E01: today's measured spread (or the pessimistic class default) plus 0.35 bps commission
per side, financing zero by construction and asserted. Spreads in 2014 to 2020 were probably
wider than today's; C4 (double costs) is the guard against that.

## Pass criteria (all four required)

* **C1**: net annualised Sharpe above 0.
* **C2**: net Sharpe above the 95th percentile of 200 random-sign nulls (seeds 0 to 199).
* **C3**: net positive in at least 3 of the 5 calendar years 2015 to 2019, AND over the last 12
  months of the sample.
* **C4**: net Sharpe above 0 with spread and commission doubled.

Reported, not deciding: gross Sharpe, metals and energy separately, deflated Sharpe at N = 297
(295 documented by 19 September, plus E01 and E02; E04 is a measurement and adds nothing).

## What each outcome means

* All four pass: a candidate for demo paper trading on metals and energy. Then, and only then,
  the E01 subgroup becomes a lead.
* Any fail: the E01 subgroup was noise, as E01 said it probably was.

## Counting

One trial, one fixed rule.
