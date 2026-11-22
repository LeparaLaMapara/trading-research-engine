# Agenda item 1 data check: JSE ETFs, proxies, SA cash rate (2026-11-22)

Script `lab/etf/data_check.py`, output `docs/results/etf-data-check-2026-11-22.json` (sha256 of every
raw file inside; raw cache `$ARTIFACT_ROOT/research-loop/etf-data-2026-11-22/`). Data quality only:
no return, Sharpe, drawdown or rule signal was computed. Proxy tracking uses monthly returns before
HOLDOUT_START (2024-09-16) only. **0 trials.**

Sources: Yahoo Finance chart API (daily, with dividend and split events), FRED fredgraph.csv.

## Findings

1. **Yahoo .JO history starts 2009-01 at the earliest**, not 2000 (STX40, GLD, SYGWD
   `firstTradeDate` 2009-01-01/02). The agenda note "yfinance .JO from 2000" was wrong. Only the
   J200 price index (^J200.JO) goes back to 2000.
2. **Yahoo's adjusted close for JSE listings is NOT a total return series.** On ex-dates the
   adjclose/close ratio moves by about 1/100 of the dividend over the price (STX40 2026-10-21:
   dividend 142.37 ZAc on 10,329 ZAc, step 0.014% instead of 1.4%). 0 of 105 STX40 dividend steps
   match; STXGOV 0/32, STXPRO 0/68, ETFBND 0/29, SYGWD 6/26, CSPROP 4/57. The same check passes
   31/31 on URTH (US), so the check is sound and the fault is Yahoo's JSE unit handling.
3. **About half the JSE dividends are listed twice** (same amount on two dates a few weeks
   apart). After keeping the later date of each pair: STX40 105 to 55, STXGOV 32 to 22, STXPRO
   68 to 41, ETFBND 29 to 25. De-duplicated trailing yields are plausible (STX40 1.9% to 4.0% a
   year 2013-2025; STXPRO 6.1% to 9.0%; ETFBND 7.4% to 9.8%); raw ones were double (STX40 up to
   9.5%, STXGOV up to 20.9%). STXGOV de-duplicated is still 8.6% to 12.5%: UNVERIFIED against the
   Satrix fact sheet.
4. **Yahoo's JSE dividend record is incomplete** (amendment after the first run, same day;
   per-year counts now in the JSON): no dividends at all before 2013 for STX40 (2009-2012),
   SYGWD (2009-2012) and CSPROP (2011-2012), though bars exist; ETFBND has none in 2021;
   fewer than the usual count in STX40 2017, STXGOV 2020-2022, SYGWD 2018 and 2021, CSPROP 2017.
   From 2024 most SYGWD and CSPROP amounts are about 100x too small (rand, not cents: SYGWD
   2024-07-10 0.2292 on a price near 7,900 ZAc; CSPROP 10 events 2024-04 to 2026-10); these are
   probably the few "matched" adjclose steps in point 2. STXGOV 2026-01 and 2026-07 are flagged
   by the same rule (possibly small coupons, UNVERIFIED). The later date of each duplicate pair is
   ASSUMED to be the ex-date (UNVERIFIED; it can move a dividend across a month-end). So the
   rebuilt total return is only trustworthy where the record is complete: STX40 2013-2026 except
   2017; STXPRO 2017-2026; STXGOV 2023-2025; ETFBND 2022-2026; SYGWD 2013-2024-06 except 2018
   and 2021; CSPROP 2013-2024-03 except 2017. SYGWD yields only about 1% a year, so its gaps
   matter little; CSPROP (about 6%) and the bond funds (about 9%) matter a lot.
5. **Total return must be rebuilt** from close plus de-duplicated dividends (done in the script,
   `rebuild_tr`). Feeder funds STXWDM, STX500 and GLD show no dividends (accumulating or none).
6. **Bad prints:** STX40 2025-04-25 printed 84.44 instead of about 8,412 (100x unit error,
   removed). USDZAR=X has 4 stray prints (2024-11-15, 2025-01-15 to 17, about 18% off), removed.
   GLD has gaps of 32, 23 and 11 days in 2015-2016. CSPROP traded only about monthly from
   2011-05 to 2012-07 (16 gaps over 7 days), so it is usable from about 2012-08. Zero-volume bars
   are common (CSPROP 2,892 of 3,576, GLD 3,668 of 4,352): Yahoo JSE volume is not trustworthy,
   and these ETFs may be thin (spreads still UNVERIFIED, agenda 2b).
7. **Proxy tracking, monthly, pre-holdout** (corr, annual tracking error):

| proxy | target | months | corr | TE |
|---|---|---|---|---|
| SYGWD (2009) | STXWDM | 85 | 0.994 | 1.8% |
| CSPROP (2011) | STXPRO | 90 | 0.974 | 5.4% |
| ETFBND (2019-06) | STXGOV | 51 | 0.862 | 4.3% |
| ^J200 price | STX40 TR | 187 | 0.997 | 1.3% (dividend gap) |
| URTH x USDZAR | STXWDM | 85 | 0.958 | 4.7% |
| synthetic bond (FRED 10y, D=7) | STXGOV | 51 | 0.556 | 7.7% |
| synthetic bond | ETFBND | 62 | 0.756 | 6.7% |

   ETFBND and CSPROP tracking includes years with missing or wrongly scaled dividends (ETFBND
   2021, CSPROP from 2024-04), so their true tracking is probably better than shown; the ETFBND
   drop from 0.928 (Yahoo adjclose) to 0.862 (rebuilt) is consistent with the missing 2021
   coupons. The synthetic bond tracks badly (FRED's yield is a monthly average, not a month-end value):
   **not usable** as the bond leg. SYGWD is a near-perfect stand-in for STXWDM.
8. **Cash leg:** FRED IR3TIB01ZAM156N (SA 3-month interbank) runs 1980-12 to 2026-10 with no
   missing months. Fit for the cash benchmark (agenda 1c). IR3TTS01 ends 2023-12, INTDSR 2013-04.

## Windows for a 5-class monthly test (SA equity, global equity, SA bonds, property, gold)

| set | start | months | vault if last 40% | dev / vault months if HOLDOUT_START |
|---|---|---|---|---|
| A: target ETFs only | 2020-05 | 79 | from 2024-04 (47 dev) | 52 / 27 |
| B: real ZAR proxies (SYGWD, ETFBND, CSPROP) | 2019-06 | 90 | from 2023-12 (54 dev) | 63 / 27 |
| C: synthetic bond | 2011-05 (2012-08 for clean CSPROP) | 187 | from 2020-09 | 160 / 27 |

The months to 2026-11 include the partial current month.

## Verdict

Yahoo is not a trustworthy total-return source for JSE ETFs: its adjusted close ignores
dividends, and its dividend list is doubled, starts in 2013, has holes and switches units in
2024. Prices are usable (after removing one 100x print); dividends need an issuer source
(Satrix, Sygnia, 1nvest, 10X distribution histories) before any test. Window B (from 2019-06)
and window C are only as good as that dividend source. With a real bond leg, the longest honest window is
2019-06 onward: 90 months, about 54 of them development months. That is too short for a monthly
10-month moving-average rule to show a drawdown difference with any power (hypothesis; the
pre-registration must size it). The SA bond class is the binding constraint. Options for the
pre-registration (not chosen here): (i) drop the bond class and run 4 classes from 2012-08;
(ii) keep set B and accept low power; (iii) find a month-end SA bond total-return index (for
example the JSE ALBI, which needs a licence or an issuer file).
