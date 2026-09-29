# A01 pre-registration: audit of the two live rules with stronger tests

Written 29 September 2026, committed and pushed before the audit runs. An audit spends no slot
and adds no trials (docs/programme/README.md, rule 3): it re-tests rules already counted, and
it can only demote.

## What is audited

The two rules trading live:

* **E07**: Ethereum 20-day trend, stop only, ETHUSD daily bars up to E05's END date, cost
  11.94 bps per round trip, E05's financing, 365 bars a year (exactly E07's run).
* **E08 on USDSGD**: the same rule on USDSGD daily bars up to 2026-09-19, the cost E08 used
  (2.7 bps per round trip), the broker's fee both directions, 260 bars a year (exactly E08's run).

Same code (`lab/eth_trend.simulate`), same data window, same costs. Nothing is tuned.

## Why

Both rules passed with tests sized for a laptop: 200 random-sign null draws, no confidence
interval on the Sharpe, and a deflated Sharpe that was reported but not required. Databricks
makes the stronger versions affordable.

## Criteria (all three must hold, or the rule is demoted)

* **K1, null:** net Sharpe above the 99th percentile of 10,000 random-sign null draws with the
  same costs and financing (seeds 0 to 9,999).
* **K2, uncertainty:** stationary block bootstrap of the daily net returns (Politis and Romano,
  mean block 20 days, 10,000 resamples, seed 0): fewer than 10% of resamples have a net Sharpe
  at or below zero.
* **K3, stability:** net Sharpe positive in both halves of the sample, split at the middle day.

Reported, not deciding: the 90% bootstrap interval, the deflated Sharpe at N = 306, and for
USDSGD the net Sharpe at the cost measured so far (flagged as based on few hours of quotes).

## What happens after

* A rule that fails is demoted: `trader_step.py` stops opening new trades for it (its open
  position keeps its stop and is closed by the rule's own exit). Written to the register as
  `A01 FAIL` for that rule.
* A rule that passes keeps trading. Nothing is promoted by an audit.

## Expectation, written before running

With a net Sharpe of 0.15 over eleven years, USDSGD's standard error is about 0.3, so it is
likely to fail K2. Ethereum (0.80 over about seven years) is likely to pass K1 and K2. This is
written down so the criteria cannot later be said to have been chosen after seeing the answer:
they are the standard ones, and they are fixed here.

## How it runs

`scripts/a01_audit.py`, run on Databricks through `databricks-run.yml`. It writes
`docs/results/A01-live-rules-audit.json` and records no trials.
