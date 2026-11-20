# Venues and their costs (built 2026-11-20)

Charter rule 5: price every candidate on its target venue before any fit; reject if expected
gross edge < 3x cost. Every number below carries a source: a script in this repo (path +
commit) or a URL read on the date shown. UNVERIFIED means no source was found; such a number
may not be used to pass a cost gate, only to fail one.

## 1. cTrader CFD (IC Markets, the account the live engine already uses)

Source: `lab/venues/ctrader_costs.py` (same cost model as every backtest: `zoo.portfolio.cost_table`,
measured median spreads from `data/spread_summary.json`, exported 2026-09-22; measured swap
rates from `data/swaps.json`, captured 2026-09-22; plus commission), output
`docs/results/venues-ctrader-costs-2026-11-20.json`. Basis points of the instrument's average
price over the panel, not today's price.

| class | round trip, bps (median) | financing, % of notional a year (median) | how measured |
|---|---|---|---|
| fx_major (7 measured) | 0.95 | 1.16 | spread measured; swap measured |
| fx_cross | 1.37 | 0.89 | 5 of 9 spreads measured, 4 assumed 3 bps |
| index | 2.70 | 5.90 | DE40, US500, AUS200, HK50 measured (p75, few hours); others assumed 2 bps |
| metal | 5.03 (gold 1.41, silver 8.65) | 1.73 | measured |
| energy | 8.10 (WTI 3.50) | 13.52 (WTI 22.26) | WTI measured; gas assumed |
| bond (BUND, USTBOND) | 2.40 | 1.00 | ASSUMED both (no telemetry) |

* Commission: measured $0.03 per side per 0.01 lot on EURUSD (rounded; true about $0.035),
  fills at the quote, slippage 0.013 pip better on average over 38 fills
  (`docs/results/E04-fill-cost.md`).
* Financing is charged every night held, both directions on most symbols. For a position held
  all year it is 1.5x to 3.2x the whole gross edge of every slow trend rule tested
  (`docs/results/e19-cost-split-2026-11-19.md`). **Verdict: cTrader is for intraday holds only**
  (no rollover crossed), never multi-week holds.
* Small-account constraint: 0.01 lot minimum; the signed live limits cap risk per trade. Exact
  balance is kept out of this public repo.

## 2. Interactive Brokers, micro futures (paper first)

Read 2026-11-20. IBKR and CME pages refused automated fetches (HTTP 403 / timeouts), so the
IBKR and CME numbers are search-engine extracts of the URLs shown, of uncertain age: **confirm
in TWS before any of them passes a cost gate.** NFA was read in full.

| item | value | source |
|---|---|---|
| IBKR Pro commission, micro group (MES, MNQ, M2K, MYM, 2YY, 10Y, MCL, MGC, SIL ...) | $0.25 per side (fixed; tiered also $0.25 up to 1,000 contracts a month) | https://www.interactivebrokers.com/en/pricing/commissions-futures.php ; https://www.interactivebrokers.com/en/trading/micro-futures-comparison.php |
| Exchange fee MES, MNQ, M2K (CME) / MYM, yield futures (CBOT) | $0.35 / $0.35, $0.30 | https://www.interactivebrokers.com/en/accounts/fees/CME.php ; .../CBOT.php |
| Exchange fee MGC (COMEX) / MCL (NYMEX) / E-micro FX M6E | $0.70 / $0.50 / $0.24 | .../COMEX.php ; https://investors.interactivebrokers.com/en/index.php?f=268 ; CME.php |
| Exchange fee SIL, M6A, M6B, ZN | UNVERIFIED | |
| CME regulatory recovery | $0.01 per side | CME.php |
| NFA assessment | $0.01 per side since 2026-07-01, $0.02 from 2027-07-01 | https://www.nfa.futures.org/faqs/members/nfa-assessment-fees.html |
| Specs | MES $5 x index, tick 0.25; MNQ $2, 0.25; MYM $0.5, 1; MGC 10 oz, $0.10; SIL 1,000 oz, $0.005; MCL 100 bbl, $0.01; 10Y $10 per bp; M6E tick $1.25 | https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html (and the MNQ, MYM pages); https://www.cmegroup.com/education/lessons/micro-gold-and-micro-silver-futures-product-overview ; https://www.cmegroup.com/notices/ser/2020/08/SER-8635.pdf (SIL tick, overrides the micro metals page) ; https://www.cmegroup.com/trading/energy/files/micro-wti-crude-oil-futures-fact-card.pdf ; https://www.cmegroup.com/articles/2024/understanding-yield-futures.html ; https://www.cmegroup.com/markets/microsuite/fx.html |
| Spread | MES about 1 tick in regular hours (blogs only); all others UNVERIFIED | https://optimusfutures.com/blog/micro-vs-mini-futures/ |
| Margin (exchange maintenance) | MES 2,919; MNQ 4,574; MYM 1,698; MGC 2,140; SIL 4,325; MCL 930; 10Y 352; M6E 231; M6A 193; M6B 187 USD per contract (undated); IBKR's own: UNVERIFIED | https://www.ampfutures.com/trading-info/margins |
| Roll | equity index, FX, ZN quarterly (standard, not cited); MGC every 2 months; MCL monthly; yield futures monthly | CME spec pages / fact cards |
| Market data | CME Level 1 non-pro about $1.55 per exchange a month (4 exchanges) | https://investors.interactivebrokers.com/en/pricing/market-data-pricing.php |
| SA residents | eligible (country list); entity serving SA and inactivity fee UNVERIFIED; funding uses the SARB offshore allowance | https://www.interactivebrokers.com/en/accounts/open-account-country-list.php |

Round trip per contract (fees both sides + 1 tick spread), at the last pre-holdout close of the
spot proxy: `lab/venues/futures_costs.py` -> `docs/results/venues-futures-costs-2026-11-20.json`.

| contract | notional, USD | round trip, USD | round trip, bps |
|---|---|---|---|
| MES | 28,119 | 2.49 | 0.89 |
| MNQ | 38,992 | 1.74 | 0.45 |
| MYM | 20,700 | 1.74 | 0.84 |
| MGC | 25,776 | 2.94 | 1.14 |
| SIL | 23,776 | 6.02 | 2.53 (fee assumed) |
| MCL | 6,919 | 2.54 | 3.67 |
| M6E | 13,842 | 2.27 | 1.64 |
| M6A | 6,702 | 2.02 | 3.01 (fee assumed) |
| M6B | 8,199 | 1.65 | 2.01 (fee assumed) |

* **Roll cost** (arithmetic from the table, one round trip per roll at full position):
  quarterly contracts about 4 x 1-3 bps = 4-12 bps a year; MCL monthly 12 x 3.67 = 44 bps a year.
  Compare cTrader financing of 590 bps (indices) and 2,226 bps (WTI) a year. Futures carry the
  interest rate inside the price (basis), which an excess-return backtest already nets out;
  there is no broker financing spread on top.
* **Granularity is the binding constraint, not cost.** One contract of each of the nine above is
  about $172k of notional (sum of the table). A trend book needs whole contracts sized to
  volatility; with one contract as the smallest unit, a diversified micro-futures book needs
  capital far above the current account (hypothesis, to be quantified before E19 is
  pre-registered: agenda item 1). Yield futures (10Y, $10 per bp) and micro FX are the finest.

## 3. EasyEquities, JSE ETFs and shares (hand executed)

Read 2026-11-20. Main source: EasyEquities Cost Profile, 12 Feb 2026,
https://resources.easyequities.co.za/EasyEquities_CostProfile.pdf (costs shown ex VAT).

| item | value | source |
|---|---|---|
| Brokerage | 0.25% per side, min 1c, no max | Cost Profile p.2 note 1 |
| Settlement and admin (Strate) | 0.0795% per side | Cost Profile p.2 note 3 |
| Investor protection levy | 0.00031% per side | Cost Profile p.2 note 4 |
| VAT | 15% on applicable costs | Cost Profile p.2 |
| STT | 0.25% on purchases of shares; ETFs that are CIS participatory interests exempt (STT Act s8(1)(f)); TFSA "N/A" | https://www.sars.gov.za/types-of-tax/securities-transfer-tax/ ; https://www.acts.co.za/securities-transfer-tax-act-2007/8__exemptions |
| STT on NewGold (a debenture, not a CIS) and whether EasyEquities waives STT on ETF buys in a ZAR account | UNVERIFIED (check a contract note) | |
| Advanced orders (limit, stop) | +0.35% per trade, ZAR account | Cost Profile p.3 note 14 |
| Monthly fee | none; optional R25 Thrive fee | Cost Profile pp.2-3 |
| Execution | at the live order book price; screen prices delayed 15 min; desk 09:05-16:40 | https://support.easyequities.co.za/support/solutions/articles/5000619259 |
| Bid/ask spread of ETFs | UNVERIFIED for every ETF: measure it | |
| TFSA | R46,000 a year from 1 Mar 2026, R500,000 lifetime, 40% penalty on excess | https://www.sars.gov.za/types-of-tax/tax-free-investments/ |

**Round trip ex spread, VAT on all fees (upper bound): 2 x (0.25 + 0.0795 + 0.00031)% x 1.15
= 0.76%.** Shares in the ZAR account add 0.25% STT on the buy.

ETFs for item 3 (issuer fact sheets at 30 Sep 2026; GLD at 31 Dec 2025):

| ETF | asset | TER incl VAT | inception |
|---|---|---|---|
| STX40 | SA equity (J200) | 0.10% | 2000-11-27 |
| STXWDM | global equity (feeder, ZAR) | 0.25% | 2017-07-25 |
| STX500 | US equity (feeder, ZAR) | 0.25% | 2017-07-25 |
| STXGOV | SA government bonds | 0.25% | 2020-05-07 |
| STXPRO | SA property (index changed to J803 on 2026-06-19) | 0.33% | 2017-02-24 |
| GLD (NewGold) | gold | 0.30% a year sales charge | 2004-11-01 |

Sources: https://satrix.co.za/fund/mdd/STX40 (and /STXWDM, /STX500, /STXGOV, /STXPRO);
https://resources.easyequities.co.za/ETFs/ETF%20Factsheets/ABSA/GLD.pdf. A 5-class window
"from the latest inception" starts in May 2020 (STXGOV), too short for a monthly rule: item 3
must use index histories or older bond proxies for the bond leg.

## 4. Use in the cost gate (charter rule 5)

| venue | cost per unit of turnover | holding cost a year | fit |
|---|---|---|---|
| cTrader CFD | 0.5 to 4 bps (FX, gold, indices) | 1 to 22% of notional | intraday only |
| IBKR micro futures | 0.5 to 4 bps round trip | roll 4 to 44 bps | slow trend, IF capital allows whole contracts |
| EasyEquities ETFs | 0.76% round trip + spread | TER 0.10 to 0.33% | monthly or slower, unlevered |

Rule of thumb: annual cost = turnover per year x round trip / 2 + holding cost. Example:
tsmom_12m (12.7 turnover a year, `docs/results/e19-cost-split-2026-11-19.md`) on micro futures
at 2 bps is about 13 bps a year plus roll 10-44 bps: well inside the 3x gate for a gross edge of
a few percent. On EasyEquities at 0.76% round trip it would cost about 4.8% a year: fails; only
rules switching about once or twice a year per asset fit there.
