# Agenda item 1: cost gate for the monthly ETF trend filter on EasyEquities (2026-11-23)

Script `lab/etf/power.py` (run on commit 09c5000 plus this change), output
`docs/results/etf-power-2026-11-23.json`. **Synthetic returns only**: no real JSE return, price or
dividend series was read, and the rule was never run on real data. **0 trials. No programme slot
spent; nothing registered.**

## What was priced

The pre-registration candidate from agenda row 5a: Faber's 10-month moving-average filter, each of
4 equal slots (SA equity, global equity in rand, SA listed property, gold) holds its ETF when the
month-end total-return index is above its 10-month simple average, else cash; benchmark equal-weight
buy-and-hold; both rebalanced monthly; cost charged on traded notional. Window planned 2013-11 to
2026-09 (155 months). The 5-class version (bonds from 2019-06) was not taken further: shorter
(79 months), lower power, and its ETFBND leg is unverified.

Source of the rule: Faber, "A Quantitative Approach to Tactical Asset Allocation", SSRN 962461,
February 2013 update (Journal of Wealth Management, Spring 2007). Text read from
https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf (PDF sha256 f2dabb6d...24bdd3f,
text sha256 199658f7...8c04, kept outside the repo in `$ARTIFACT_ROOT/research-loop/faber-2026-11-23/`).
Quotes: "Buy when monthly price > 10-month SMA." "Sell and move to cash when monthly price < 10-month
SMA." "All data series are total return series including dividends" "Taxes, commissions, and
slippage are excluded" "less than one round-trip trade per asset class per year" "Drawdown is
reduced from 46% to less than 10%" "On average, the investor is 70% invested." (US-centric 5 class
portfolio, 1973 to 2012.)

Venue cost (docs/research-loop/VENUES.md): 0.38% per side ex spread (brokerage, settlement, levy, VAT);
ETF half spread UNVERIFIED (0.25% base, 0.5% stress, 0 as a best case). Cash interest at the broker
UNVERIFIED (not found on any public EasyEquities page read today), so two cash legs: `mmf` a
money-market fund at 7% less 0.3%, both legs traded per switch; `acct` account cash at 7% less 2%,
asset leg only.

Gate (charter rule 5) in Sharpe units, because the rule's value is risk reduction (its return is
about equal to buy-and-hold before cost): gross edge = median Sharpe gain of the rule over
buy-and-hold with no trading cost and cash at 7%; cost = the Sharpe the venue takes away (trading
plus cash drag), both against one common 7% cash rate. Pass needs gross >= 3 x cost.

## Numbers (4,000 paths, 155 months, seed 20261123)

| world | cash leg | half spread | gross Sharpe gain | net Sharpe gain | cost %/yr | gate ratio |
|---|---|---|---|---|---|---|
| strong trend (bear 20% of months, -2.5%/month) | mmf | 0.25% | +0.113 | -0.148 | 2.2 | 0.43 |
| strong trend | acct | 0.25% | +0.112 | -0.086 | 1.6 | 0.57 |
| strong trend | mmf | 0 | +0.112 | -0.051 | 1.4 | 0.69 |
| strong trend | acct | 0 | +0.104 | -0.043 | 1.3 | 0.71 |
| strong trend | mmf | 0.5% | +0.109 | -0.249 | 3.0 | 0.30 |
| mild trend (-1.5%/month) | mmf | 0.25% | +0.011 | -0.268 | 2.3 | 0.04 |
| no trend (iid) | mmf | 0.25% | -0.062 | -0.355 | 2.4 | below 0 |

About 1.7 to 2.0 switches per asset a year (Faber: under one round trip a year, consistent).

Fable red-team (2026-11-23, its own synthetic runs): the cost arithmetic is right and not double
counted; it found the first version measured Sharpe against each leg's own cash rate, hiding the
account-cash drag (fixed above, numbers rerun). It also found the strong-trend world is WEAKER than
Faber's reported effect (drawdown ratio 0.45 vs about 0.2). In a world built to match Faber's
drawdown cut (an in-sample ceiling), the gate ratio is 1.3 (mmf, 0.25% half spread) to 2.6 (account
cash at 6.7%), and reaches 4.0 only with account cash near the interbank rate AND zero spread
together. A +-4% band around the average halves switching (1.74 to 0.79 a year) and lifts the ratio
to 1.3-1.4 (realistic world) or about 5 (Faber-strength world, account cash 6.7%), but creates no
edge on its own.

Power of the planned pass rule (maxDD <= 0.7 x buy-and-hold and Sharpe at most 0.1 lower), for the
record: false pass 4.6% (iid null) and 7.5% (fat-tailed, volatility clustering null); power 39%
(strong trend), 16% (mild). The 45-month vault alone: 11% false pass, 30% power.

## Verdict

**FAIL at the cost gate: EDGE_DESTROYED_BY_COSTS** (pre-test, 0 trials). At 0.38% a side plus any
spread, switching a slot about twice a year costs 1.3% to 3.0% a year, which removes more than the
rule's whole expected risk benefit in every realistic configuration (gate ratio 0.04 to 0.71, needs
3). It could only pass with all of: a Faber-strength trend effect in SA assets, account cash that
earns close to the interbank rate, near-zero ETF spreads, and a banded (slower) rule. The first is
an in-sample US result; the other two are unverified venue facts (agenda 2b). Do not spend a slot
until 2b verifies cash interest and spreads.
