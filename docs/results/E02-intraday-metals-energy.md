# E02 result: intraday momentum on metals and energy, 2014 to 2020. FAIL

Run on 22 September 2026 after the pre-registration was committed (d7b85e9). Raw numbers:
`E02-intraday-metals-energy.json` (data hash 703f5e973e0ba1c5). Re-run with
`python -m scripts.e01_intraday --experiment E02`.

## What was tested

E01's exact rule on XAUUSD, XAGUSD, XAUEUR (from October 2014) and XTIUSD (from June 2016),
up to 16 September 2020: 1,478 portfolio days that no E01 day overlaps. XBRUSD has no hourly
history before 2020 and was dropped, as the pre-registration allowed.

## Result

| criterion | needed | got | |
|---|---|---|---|
| C1 net Sharpe | above 0 | -0.59 | fail |
| C2 beat the random-sign null | above -0.56 | -0.59 | fail |
| C3 years positive, and last 12 months | 3 of 5, and positive | 0 of 5, last 12 months +16% | fail |
| C4 net Sharpe at double costs | above 0 | -1.51 | fail |

## What it means

Unlike E01, there is something here before costs: gross Sharpe **+0.34** on data that did not
suggest the idea. Costs take all of it and more. This is EDGE_DESTROYED_BY_COSTS, the same
verdict as 14 of the 20 candidates classified on 20 September: a small, real tendency that is
too small to pay the spread every day. The E01 subgroup was not pure noise, but it is not
tradeable at this broker.

Metals alone were -0.55 net and energy -0.21 net. Neither is a lead.

## Budget

3 of 10 spent. 0 strategies passed (E04 passed, but it is a measurement).
