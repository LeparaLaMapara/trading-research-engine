# E10 pre-registration: the evidence families, across every instrument the broker offers

**Status: registered 21 October 2026, committed and pushed to main before the screen is run
on real prices.** Decided by the research lead under the owner's standing instruction to make
research decisions without an approval round, and under the owner's design of 21 October 2026
("the objective is to learn, not earn: maximise decisive verdicts per week"). This spends the
last slot of programme P1. The code that scores it, `learning/screen.py` and
`learning/families.py`, is committed in the same change, so the rules below are frozen as code.
It has only been run on synthetic random-walk prices (tests/test_learning_screen.py).

## The idea in plain words

Nine single experiments in P1 asked one question each about one or two instruments. That is
slow learning. This experiment asks six well-known questions of sixty instruments at once,
with one method and one honest count of how many things were tried, and sorts every answer
into "worth a forward test", "ruled out at this broker's costs" or "cannot tell yet". The
"worth a forward test" ones go to the forward fleet (paper or demo), where a sequential test
decides them; none becomes a live rule from this experiment.

## Sources (identifiers resolved through Crossref on 21 October 2026; full texts not stored)

The rules tested are the standard textbook forms of these published effects, written out in
`learning/families.py`. No sentence of any paper is relied on, so no quote is claimed.

| family | source |
|---|---|
| time-series momentum | Moskowitz, Ooi and Pedersen, "Time series momentum", JFE 2012, doi:10.1016/j.jfineco.2011.11.003 |
| short-term reversal | Lehmann, "Fads, martingales, and market efficiency", QJE 1990, doi:10.2307/2937816 |
| turn of the month | Lakonishok and Smidt, "Are seasonal anomalies real?", RFS 1988, doi:10.1093/rfs/1.4.403 |
| FX carry | Menkhoff, Sarno, Schmeling and Schrimpf, "Carry trades and global FX volatility", J. Finance 2012, doi:10.1111/j.1540-6261.2012.01728.x; Koijen, Moskowitz, Pedersen and Vrugt, "Carry", JFE 2018, doi:10.1016/j.jfineco.2017.11.002 |
| currency cross-sectional momentum | Menkhoff, Sarno, Schmeling and Schrimpf, "Currency momentum strategies", JFE 2012, doi:10.1016/j.jfineco.2012.06.009 |
| time of day | Breedon and Ranaldo, "Intraday patterns in FX returns and order flow", JMCB 2013, doi:10.1111/jmcb.12032 |
| method: PBO | Bailey, Borwein, Lopez de Prado and Zhu, "The probability of backtest overfitting", J. Computational Finance 2016, doi:10.21314/JCF.2016.322 |
| method: t bar | Harvey, Liu and Zhu, "... and the cross-section of expected returns", RFS 2015, doi:10.1093/rfs/hhv059 |

Currency **value** is not tested: it needs purchasing-power-parity or real-exchange-rate data
the engine does not hold, and a proxy would be a different claim.

Prior evidence stated so nobody mistakes this for a first look: the pre-programme zoo tested a
12-month trend, cross-sectional momentum and short reversal pooled across 24 instruments
("trend fails on this instrument set"), and carry was falsified on 19 September
(`docs/results/carry-preregistration-2026-09-19.md`). Those are already in N. Re-testing them
per instrument across 60 instruments is a different question (where, if anywhere) and every
new trial is counted again.

## Rules (exactly as coded)

Positions are -1, 0 or +1 (the broker minimum leaves no room for volatility scaling), held
from one close to the next, computed only from data up to the previous close.

| variant | rule | applies to |
|---|---|---|
| tsmom_21, tsmom_63, tsmom_252 | sign of the past 21, 63 or 252-day return | all 60 |
| reversal_5, reversal_21 | minus the sign of the past 5 or 21-day return | all 60 |
| turn_month | long on the last weekday of a month and the first three weekdays of the next | all 60 |
| carry_any, carry_1pct | sign of the base-minus-quote 3-month rate difference (only if at least 1 point for carry_1pct) | currency pairs whose two rates exist |
| us_hours_long_foreign | hold the foreign currency against the dollar from 13:00 to 21:00 UTC, H1 bars | EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF |
| xs_mom_21, xs_mom_63 | every 21 days rank 13 currencies against the dollar by past 21 or 63-day return; long the top 3, short the bottom 3 | one portfolio each |

## Data

* `data/market.db` D1 bars from 2015-01-01 (with lookback history before it) to 2026-09-15,
  the 60 instruments with the longest D1 history among those the broker lists in
  `data/swaps.json` (64 have D1 bars; the four shortest, ADAUSD, CA60, SA40 and SOLUSD, are
  left out). H1 bars for time of day.
* 3-month interbank rates (OECD via FRED), usable two months after the month they describe.
  The Singapore file is an HTML error page, so USDSGD has no carry trial.

## Costs

* Measured round-trip spread (`backtest.run.measured_cost`) plus 0.35 bps commission a side,
  charged on every change of position.
* The broker's financing fee (`zoo.financing`), charged on every held bar in both directions.
  For currency pairs the rate differential is earned or paid by direction from the
  point-in-time rates. Time of day closes before the 21:00 UTC rollover and pays none.

## Trials and N

Every variant x instrument is one trial: 60 x 6 = 360, carry 2 x 31 = 62, time of day 7,
portfolios 2: **431 trials** expected (the result records the exact count). N before is 307;
every deflated Sharpe in the result is computed at N = 307 + trials.

## Criteria (per trial)

* **IN** (forward-test candidate) only if all four hold: t-statistic of daily net returns at
  least 2.0 (all six families are replications of published results; a new family would need
  3.0), the family's PBO by CSCV (16 blocks) below 0.5, deflated Sharpe at the running N at
  least 0.5, and net Sharpe still positive at doubled costs.
* **OUT** if the one-sided 95% upper bound of the annual net Sharpe is below 0.3, the smallest
  Sharpe that serves the family goal within three years (`research/goals.py`).
* **UNDECIDED** otherwise.

## Verdict of the experiment

**PASS** if at least one trial is IN; **FAIL** if none is. A pass means forward testing (paper
on live quotes until a demo account exists), decided by an always-valid sequential test
(mSPRT, Johari, Pekelis and Walsh, Operations Research 2022, doi:10.1287/opre.2021.2135). It is
never a live order: a live rule still needs a forward IN, the deflated Sharpe bar of 0.95 at
N, and the existing trader path inside the owner's signed limits.
