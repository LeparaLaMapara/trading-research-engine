# E03 pre-registration: does order-book pressure predict the next minute, net of costs?

Written and committed on 22 September 2026, BEFORE the evaluation data exists. Experiment 3 of
10. This is the first test in the engine of a signal that is not built from prices alone.

## Hypothesis

When the resting size near the top of the book is lopsided (much more on the bid than the ask,
or the reverse), the mid price tends to move toward the thin side over the next 60 seconds, by
more than it costs to cross the spread twice, even after this engine's measured delay.

## Data

* The broker's depth feed (`depth_quotes` in `data/telemetry.db`, recorded by
  `python -m telemetry.logger --depth`), BTCUSD and ETHUSD.
* **Evaluation data: only depth recorded AFTER this document is committed**, at least 120 hours
  per symbol (5 days; crypto trades every day). Recording starts once the E04 probes finish,
  because one broker session per account means the recorder, the probes and the hourly
  dashboard job cannot all hold it at once.
* The 1.5 hours recorded on 22 September before this document (about 400,000 rows) are
  **excluded from evaluation**. They may be used only to build and check the book
  reconstruction code, which is committed before the evaluation data is read.

## The signal and the rule

* Rebuild the book from the quote events. Every second, compute the imbalance
  `I = (B - A) / (B + A)`, where B and A are the total resting sizes of the best 5 bid and
  best 5 ask levels.
* **Trade** when |I| is at least 0.6: buy when I is positive, sell when negative. Enter 2
  seconds after the signal (the engine's measured decision-to-order time) at the far side of
  the book then (the ask when buying, the bid when selling), and exit 60 seconds after entry at
  the far side then. No new signal on a symbol while a trade is open.
* Cost: the two spread crossings are in the prices above. Commission 0.35 bps per side is added.
  No financing (held one minute).

## Pass criteria (all three required)

* **C1 (prediction)**: across all one-second samples, the rank correlation between I and the
  mid-price change over the next 60 seconds, measured from 2 seconds after the sample, is
  positive with p below 0.01 on each symbol.
* **C2 (money)**: the mean net return per trade, pooled over both symbols, is above 0 with a
  t statistic above 2.
* **C3 (both)**: mean net return per trade is above 0 on BTCUSD and on ETHUSD separately.

## What each outcome means

* All pass: a candidate for demo paper trading. Its speed makes it the one experiment where
  the E04 slippage result matters most, so E04 must be read first.
* C1 passes, C2 fails: the book does predict, but not by enough to pay for crossing it. That is
  EDGE_DESTROYED_BY_COSTS, and the finding is still worth recording.
* C1 fails: NO_PREDICTIVE_EDGE.

## Counting

One trial. One threshold (0.6), one depth (5 levels), one horizon (60 s), fixed here.
