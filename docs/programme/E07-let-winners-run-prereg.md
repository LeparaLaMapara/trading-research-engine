# E07 pre-registration: the Ethereum trend rule without a profit target

Written and committed on 23 September 2026, BEFORE the test is run. Experiment 7 of 10.

## Why

E05 (live since 23 September) closes a winning trade at 1.5 times its risk. Trend-following
earns most of its money from a few long runs, and a fixed target cuts exactly those short. The
target was inherited from the order path's defaults (`scripts/live_trade.py`), not chosen from
evidence. The owner's review on 23 September asked what is being left on the table; this is the
largest candidate.

## The rule

E05 exactly (`lab/eth_trend.simulate`), except there is **no profit target**: a position closes
only at its 2-sigma stop or when the 20-day signal flips. Same data (ETHUSD daily, 24 September
2017 to 18 September 2026), same costs (11.94 bps a round trip), same 20% a year on longs.

## Pass criteria (all five required)

* **C1**: net Sharpe above 0.
* **C2**: net Sharpe above the 95th percentile of 200 random-sign nulls (seeds 0 to 199), run
  through the same no-target mechanics.
* **C3**: net positive in at least 5 of the 8 calendar years 2018 to 2025.
* **C4**: net Sharpe above 0 with costs doubled.
* **C5 (it must beat what is live)**: net Sharpe above E05's 0.58 on the same data.

Reported, not deciding: round trips, average holding period, largest single-trade gain, and the
deflated Sharpe at N = 300.

## What each outcome means

* All pass: the live engine switches from E05 to E07 (no target on new trades), by the
  programme's rule that a passing strategy the account can afford replaces the live one.
* C5 fails: the target stays. E05 keeps trading unchanged.

## Counting

One trial. It is a variant of E05, which is exactly why it is counted: trying variants of a
winner is how a backtest overfits, and N records that it was tried.
