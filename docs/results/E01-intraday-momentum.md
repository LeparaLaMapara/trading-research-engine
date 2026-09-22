# E01 result: intraday momentum, flat before the rollover. FAIL

Run on 22 September 2026, after the pre-registration was committed and pushed (commit 4054939).
Raw numbers: `E01-intraday-momentum.json` (data hash ed147b7b2af692d1). Re-run with
`python -m scripts.e01_intraday`.

## What was tested

The sign of each instrument's return from 23:00 to 12:00 UTC, held from 12:00 to 20:00 UTC,
flat before the 21:00 rollover. 23 instruments (HK50 had too few complete days), 1,836 portfolio
days from October 2020 to September 2026. No overnight financing, by construction and asserted.

## Result

| criterion | needed | got | |
|---|---|---|---|
| C1 net Sharpe | above 0 | -1.76 | fail |
| C2 beat the random-sign null | above -1.10 (its 95th percentile) | -1.76 | fail |
| C3 years positive, and last 12 months | 4 of 6, and positive | 0 of 6, and -30% | fail |
| C4 net Sharpe at double costs | above 0 | -3.09 | fail |

Gross Sharpe, before any cost, is **-0.26**. The morning does not predict the afternoon in the
direction the literature found. If anything it weakly predicts the opposite, and not by enough
to matter.

## What it means

This is NO_PREDICTIVE_EDGE, not EDGE_DESTROYED_BY_COSTS. Removing the overnight charge did what
it was meant to (costs fell to about 0.8 bps a round trip on the FX majors), but there was no
signal underneath for the saving to reveal. The random-sign null averaged -1.67, which is what
paying a spread every day for nothing costs this portfolio. E01 sits at that level.

## Not a finding

The by-class numbers show metals at +0.24 and energy at +0.04 net. These are subgroups nobody
pre-registered, picked after seeing the data, from six classes. Reporting them as a lead would
be exactly the multiple-testing error the programme exists to prevent. If a later experiment
tests metals, it has to be pre-registered as its own slot and pay for it in N.

## Budget

1 of 10 spent. 0 passed.
