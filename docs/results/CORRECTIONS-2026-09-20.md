# Corrections after adversarial review, 20 September 2026

A Red Team review of the latency laboratory (`docs/redteam/stage-a-review-2026-09-20.md`) broke
most of it. This file records what was wrong, what is now fixed, and what is retracted. The
review is the most valuable thing produced today.

## Retracted

**1. "Costs rose to 1.35 bps on EURUSD after the measurement fix."** FALSE. The fix introduced
a defect: the database connection was closed between two queries that shared it, the resulting
error was swallowed by a bare `except`, and every symbol fell through to the hardcoded class
default. The published table was a table of defaults labelled as measurements.

Repaired, with the connection held by a context manager and every fallback printed loudly:

| instrument | published this morning (wrong) | actually measured |
|---|---|---|
| EURUSD | 1.35 bps | **0.39 bps** |
| USDJPY | 1.35 bps | **0.38 bps** |
| XAUUSD | 1.85 bps | **0.45 bps** |
| BTCUSD | 7.85 bps | **2.74 bps** |

The lesson is not the arithmetic, it is that a silent `except` made dead code look like a
measurement for the length of a working day.

**2. "The edge crosses zero between 18 and 20 hours."** Not retracted as a point estimate, but
it must never again be published without its uncertainty. A block bootstrap over 300 resamples,
now built into the runner, puts the crossing anywhere from **2 to 24 hours** (median 12), finds
no crossing inside the grid in **49%** of resamples, and no edge at any delay in **23%**. The
review reached the same conclusion independently: only 2% of its replicates landed in (18h, 20h).

**3. "The tick content hash survived the schema change."** FALSE. The stored snapshot digest was
computed over 17 columns; today's function produces a different digest over 15. The parquet
file is named after a hash its own code can no longer reproduce.

**4. "86 ms behind true time."** One unlucky sample, taken with a client that accepted
Kiss-o'-Death rejection packets and a consensus rule that actively preferred them, because a
rejection is the shortest reply. With leap-indicator, stratum, mode and transmit-timestamp
validation, four independent servers, a median instead of a shortest-path rule, and DNS moved
outside the timing window, three consecutive runs give **+125, +129 and +131 ms**. Corrected
market-data latency is therefore about **343 ms for BTCUSD and 412 ms for ETHUSD**, not 302 and
371.

## Fixed

* `measured_cost`: context-managed connection, loud fallbacks, and the coverage hedge now
  actually executes.
* `lab/clock.py`: packet validation, median consensus, DNS outside the measurement, samples
  written to `clock_samples`; drift refuses to report over spans under 30 minutes after
  reporting 27 seconds per hour from two samples two seconds apart.
* `lab/replay.py`: negative delays refused (the old guard let them through and filled in the
  past); `decision_price` carried through, so slippage is no longer NULL in every row; the
  final fill's missing forward return is counted rather than silently dropped.
* `lab/decay.py`: each bucket now reports the p90 and maximum effective delay and the share of
  fills more than twice the requested delay, because over a weekend a "24h" bucket contains
  fills 36 to 96 hours late.
* `tests/test_lab.py`: the synthetic tape had `open == close`, so pricing at the close, a full
  hour of lookahead, was invisible; the turnover test used alternating positions, where
  turnover and exposure are proportional; the safety-margin test compared the target against
  the constant that produced it, so a margin of 1.0 passed; the refinement test skipped on this
  machine. All four are fixed, and 20 tests now cover the lab.

## Open, named, not yet fixed

* **Delay is confounded with time of day.** Daily bars stamp 21:00 UTC, so the fill hour is a
  deterministic function of the delay: zero delay fills at the rollover, where the measured
  EURUSD spread is roughly ten times its 15:00 value. An hour-aware cost model would separate
  them, and we cannot build one honestly yet: the recorder has covered about ten hours in
  total. This is now the main argument for the continuous recorder, ahead of any modelling work.
* **`data_hash` is decorative.** It hashes three summary numbers, so halving every price leaves
  it unchanged. It must hash the data.
* **`MEASURED_ORDER_PATH_MS` is a handshake**, not an order path. The true order path is
  measurable only from live orders, of which we have one.
* **`latency_events` double-counts** the probe import, which is why one document says 1,964
  samples and another 1,967.
* The p75 coverage hedge understates the 21:00 rollover by 4x on XAUUSD and by 31x and 33x on
  USDJPY and NZDUSD. It is a hedge, not a measurement, and it is labelled as such in the code.

## What did NOT change

The direction of every conclusion. With costs repaired to their true, lower values, the
candidate sweep is unchanged: 14 EDGE_DESTROYED_BY_COSTS, 4 NO_PREDICTIVE_EDGE, 2 inside the
luck band, 0 limited by latency. The venue re-score still flips 14 candidates positive at
futures-like costs, and the market-neutral test still separates the tree signals (xgb 0.53 to
0.63 when the long bias is removed) from the market-drift imposters (holding everything 1.06 to
0.00, the GRU 0.81 to 0.04).

And the pre-registered holdout test still failed, on the criterion it was always going to be
judged by.
