# E11 pre-registration: the dollar around the European currency fixes

**Status: registered 31 October 2026, committed and pushed before any scoring code exists.**
Programme P2, first slot. Decided by the research lead under the owner's 2026-10-31 goal
(profit on cTrader with the capital the account has now). The intraday prices have been
downloaded but no return over any window below has been computed.

## The idea in plain words

Every day the big banks set official exchange rates at fixed moments: the ECB fix (14:15
Frankfurt) and the London 4pm fix. Dealers who must deliver dollars at those fixes buy them in
advance, so the dollar rises into the fix and gives the move back afterwards. The trade: own
the dollar in the hours before the ECB fix; own the euro (or pound) in the hours after the
London fix. Nothing is held overnight, so the broker's financing never applies.

## Source (full text read)

Krohn, Mueller and Whelan, "Foreign Exchange Fixings and Returns Around the Clock", Bank of
Canada Staff Working Paper 2021-48 (Journal of Finance 2024). Quoted:

* p. 1: "The U.S. dollar systematically appreciates against all currencies ahead of the three
  major currency fixes in Tokyo, Frankfurt (the ECB fix) and London, and thereafter reverts."
* p. 1, the windows (ET): "pre-ECB fix ... 2:00 a.m. to 8:15 a.m." and "post-London fix ...
  11:00 a.m. to 5:00 p.m."; the sample is "January 1999 until December 2019".
* p. 28: Europe-window reversal returns before costs "for the euro, pound, and Swiss franc, at
  15.6%, 12.4% and 12%" a year, standard deviations "generally below 8%".
* p. 29-30, the decay: "returns ... dropped to below 5% during the last two years in our
  sample" and "some arbitrage capital is allocated to exploiting the reversal patterns".
* p. 34-35, costs: with full indicative spreads "average returns for most windows turn
  negative"; at half the spread, Sharpe ratios "ranging between 0.12 and 1.03".

So the published edge is real before costs, thin after costs, and was shrinking when the sample
ended. This experiment asks the only question that matters here: does it survive 2020 to 2026,
years the authors never saw, at this broker's costs?

## Differences from the paper, stated

1. The post-London leg exits at **16:30 ET**, not 17:00, so it never touches the rollover
   window the live guards block (execution/guards.py) and never pays financing.
2. Two currencies, not nine: the live limits allow two positions. EURUSD and GBPUSD are chosen
   because the paper reports them as the two strongest European-window currencies (USDCHF is
   reported as a diagnostic only).
3. Live trading would also skip any entry inside a news blackout. The backtest cannot apply that
   (no trustworthy calendar history; news/calendar.py explains why), so it trades every day.

## Data

* Dukascopy 5-minute bid AND ask bars, 2014-01-01 to 2026-09-30, EURUSD, GBPUSD, USDCHF
  (`npx dukascopy-node`, stored under `T:\making-money\features\intraday\m5`; file SHA-256s in
  the result). Times are UTC; windows are converted from New York time with daylight saving.
* A fill uses the OPEN of the 5-minute bar that starts at the window boundary: buy at the ask,
  sell at the bid, so the real spread at that minute is paid on every leg.
* Commission 0.35 bps of notional per side (the broker reports $3.00 per lot per side in
  `data/swaps.json`; rounded up on purpose).
* A day is dropped if any of its four fill bars is missing, or a fill has ask <= bid or a
  spread over 5 pips. The count of dropped days is reported.

## The rule (fixed here)

Each weekday d, for each of EURUSD and GBPUSD (quoted in dollars per unit of foreign currency,
so selling XXXUSD is owning the dollar):

1. Pre-ECB leg: at 02:00 ET SELL XXXUSD (long dollar); at 08:15 ET buy it back.
2. Post-London leg: at 11:00 ET BUY XXXUSD (long foreign); at 16:30 ET sell it.
3. Daily net return of the instrument = the sum of the two legs' net returns (equal notional).
4. The book = the equal-weight average of EURUSD and GBPUSD daily net returns.

## Deciding sample

**2020-01-01 to 2026-09-30.** 2015-2019 (inside the paper's sample) is reported as a
replication check and decides nothing.

## Pass criteria (all four, on the book, deciding sample)

1. Net annualised Sharpe > 0 with t >= 2.0 (the Harvey-Liu-Zhu bar for a replication of a
   published family, learning/stats.py).
2. Net Sharpe above the 95th percentile of 2,000 random-timing nulls: on each day, the same two
   holding lengths (6h15m and 5h30m) at uniformly random start times between 02:00 and 16:30
   ET, legs non-overlapping and in the same order and direction, same costs.
3. Net Sharpe > 0 with spread and commission both multiplied by 1.5.
4. Net return positive in at least 5 of the 7 calendar years 2020 to 2026 (2026 partial).

The deflated Sharpe at the running N is reported. PASS with deflated Sharpe >= 0.5 makes the
book a forward-test candidate (paper or demo first, never a live order by itself); a live rule
needs deflated Sharpe 0.95 at N (programme rule 4). PASS below 0.5 is recorded as "passes the
screen, too weak for a forward slot".

## Trials counted

10: three instruments (EURUSD, GBPUSD, USDCHF) x three leg sets (pre-ECB only, post-London
only, both) = 9 diagnostics, plus the book. All are reported; only the book decides.

## What would make me wrong

If it fails, the most likely reason is the one the authors gave: arbitrage capital found it.
If it passes, the most likely flaw is the cost assumption at 02:00 ET (Asian-to-European
handover), where a retail spread may be wider than Dukascopy's; the live check
(research/live_check.py) must measure the broker spread at that hour before any live trade.
