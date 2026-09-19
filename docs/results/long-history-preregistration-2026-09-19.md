# Long history pre-registration, 2026-09-19

Written before running.

## Question

The zoo found the classic rules negative on 2017 to 2024. Is that because trend following
does not work on these instruments, or because 2017 to 2024 was a weak window? Eight years
cannot separate the two (the 95% interval on an eight year Sharpe is roughly plus or minus 0.7).

## Data

Dukascopy daily bid candles, downloaded 2026-09-19 with `dukascopy-node`, stored under
`T:\making-money\features\dukascopy`. 38 instruments: FX majors and crosses, gold, silver,
nine equity indices, WTI, natural gas, cocoa, Bund and US T-bond. Many start 2003-05; indices,
bonds and commodities often later. Weekend and flat (high equals low) candles are dropped.
A different vendor from the broker: prices differ slightly, which is a robustness check in
itself.

## Candidates (count in N)

`long_risk_parity`, `ewmac`, `breakout`, `tsmom_12m`, and `ens_rules3` (equal blend of the
three trend rules). No fitted models: the question is about the rules.

## Costs

Same machinery: spread and commission from the broker cost model of the mapped symbol;
financing at the MEASURED broker fee of the mapped symbol, class median otherwise, 1% for
bonds and cocoa (assumed).

## Reporting

Net Sharpe for 2004-2008, 2009-2016, 2017-2024-09-15 separately and pooled, with block
bootstrap intervals. Nothing is read after 2024-09-15 (the holdout stays locked).

## Reading the result

* Trend positive over 2004 to 2016 and negative after: a regime or decay, UNRESOLVED.
* Trend negative throughout: FALSIFIED for this universe and cost structure.
* Trend positive throughout with a pooled DSR >= 0.95: SURVIVED, and 2017-2024 was bad luck.
