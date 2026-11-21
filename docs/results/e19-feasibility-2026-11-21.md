# E19 feasibility: capital for a whole-contract micro-futures trend book (2026-11-21)

Script: `lab/e19/feasibility.py` (thresholds committed in ce09acb before the first run).
Output: `docs/results/e19-feasibility-2026-11-21.json`. Window 2004-01 to the holdout start
(vault sealed). Costs and position rounding only: no mean P&L, Sharpe or mean rounding error
was computed. **0 trials.**

Book: tsmom_12m (sign of 12-month momentum), equal risk per market (the E19 book of
`zoo/portfolio.portfolio_returns` scaled to dollars), diversification multiplier 2.0 (ASSUMED),
nearest whole contract. Universe: MES, MNQ, MYM, MGC, SIL, MCL, M6E, M6A, M6B, 10Y (M2K and
2YY dropped: no proxy). 10Y proxied from USTBOND with ASSUMED duration 16. Headline uses
today-like contract sizes (last pre-holdout price).

## Headline (fixed contract size, with 10Y)

| capital USD | corr to ideal, vol 20% | markets held 90% of days | cost % cap/yr | corr, vol 10% | held | cost |
|---|---|---|---|---|---|---|
| 10,000 | 0.49 | 0/10 | 0.58 | 0.11 | 0/10 | 0.05 |
| 25,000 | 0.71 | 4/10 | 0.66 | 0.57 | 0/10 | 0.27 |
| 50,000 | 0.90 | 5/10 | 0.80 | 0.71 | 4/10 | 0.33 |
| 100,000 | 0.98 | 8/10 | 0.82 | 0.90 | 5/10 | 0.40 |
| 150,000 | 0.99 | 9/10 | 0.81 | 0.95 | 6/10 | 0.41 |
| 250,000 | 1.00 | 10/10 | 0.81 | 0.98 | 8/10 | 0.40 |

Pre-set feasibility (corr >= 0.90, >= 8 of 10 markets held, cost <= 0.5%/yr):
- vol target 10%: **minimum feasible capital $250,000** (same without the 10Y leg).
- vol target 20%: none on the grid. Rounding stops mattering at $100,000 (corr 0.98, 8/10 held),
  but the unbuffered book's own churn plus rolls costs 0.81%/yr at every capital from $100k up,
  above the 0.5% cap. That cap was set too tight for a 20% vol book (hypothesis: a position
  buffer would cut it), but it was fixed in advance, so the verdict stands as written.
- Historical contract sizes (smaller early on) flatter the answer: corr 0.96 at $50k (vol 20%),
  and by era at $25k: 2004-08 0.93, 2009-16 0.91, 2017-24 0.84. The headline uses today's sizes.
- Margin at $100k, vol 20%: median 18% of capital (exchange margins, UNVERIFIED).

## Verdict

A diversified micro-futures trend book needs about **$100,000 (20% vol) to $250,000 (10% vol)**
before whole contracts stop distorting it. Below $25,000 fewer than half the markets can be held
at all and the book does not resemble the strategy that would be tested. Futures costs are not
the problem (0.4% to 0.8% of capital a year); contract size is. E19 should not spend a programme
slot until capital of that order is available.
