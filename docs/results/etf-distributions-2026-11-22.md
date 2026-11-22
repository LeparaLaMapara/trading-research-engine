# Agenda item 1e: issuer distribution histories (2026-11-22, out-of-loop session)

Scripts `lab/etf/mdd_fetch.py` (fetch; sources and CDX queries in its docstring) and
`lab/etf/dist_extract.py` (parse, cross-check, rebuild, ex-date test), output
`docs/results/etf-distributions-2026-11-22.json` (every number below, each source URL and its
sha256). Raw PDFs stay in `$ARTIFACT_ROOT/research-loop/etf-dist-2026-11-22/` (59 MB, 228 kept),
not in this public repo. Data quality only: no rule or signal was computed, stated returns are read
only from documents dated before HOLDOUT_START (2024-09-16), and the ex-date price test uses only
dividend pairs before it. Distribution AMOUNTS from 2024-09 on were compared (data, not returns).
**0 trials.**

## Sources

- Live issuer sites: Satrix product pages return a server error (500); the public fact sheet link
  `satrix.co.za/fund/mdd/<code>` works (3 requests: STX40, STXPRO, STXGOV, last 4 amounts each).
  Sygnia is behind a bot wall (Incapsula) and 1nvest returns 403: **recorded as blocked, not
  bypassed**.
- Wayback Machine copies of Satrix documents (archive.org CDX), fetched 2 s apart: 441 PDFs under
  `/media/` (2017 to 2026 fact sheets) and the older Satrix 40 documents matching
  `satrix ?40|stx40|top ?40` (2006 to 2016: quarterly fact statements, distribution finalisation and
  salient-dates announcements). 573 files read, 3 not retrievable (Wayback 404).
- Wayback holds only 2021+ documents for Sygnia, 1nvest and 10X, none covering the gap years of
  SYGWD, CSPROP or ETFBND, so those three were **not** verified.

## Findings

1. **Satrix 40 (STX40) dividends now known from 2010-Q3.** 51 issuer quarters (2010-Q3 to
   2026-Q3). The 10 quarters 2010-Q3 to 2012-Q4 are missing from Yahoo entirely; issuer amounts
   fill them. 2009-01 to 2010-06 (6 quarters) stay unknown: no archived document covers them.
2. **Where both exist, Yahoo's de-duplicated amounts match the issuer** within 1%:
   - STX40: 39 of 40 quarters 2013-2026 (not 2018-Q4: issuer 16.60 cps, Yahoo 15.19). One issuer
     conflict, 2014-Q4 (21.21 vs 21.65 in two documents; excluded from the check, Yahoo's 21.21
     used). No issuer document for 2015-Q1 to 2016-Q2 or 2019-Q1 to 2020-Q4.
   - STXPRO: 21 of 21 (2017-Q3 to 2026-Q3; not checked 2018-Q3 to 2020-Q2, 2022-Q2 to 2023-Q3,
     2025-Q2 and Q3).
   - STXGOV: 14 of 14 (2020-21 half-yearly, 2024-Q2 to 2026-Q3 quarterly; not checked 2022-2023).
     This includes 2025-Q2 4.57 and 2025-Q4 1.58 cps, so the data check's flags on STXGOV
     2026-01 and 2026-07 ("100x too small?") were **false alarms**: genuinely small payouts.
3. **Acceptance test against the issuer's own stated returns** (fund, NAV, income reinvested;
   1 to 5 year windows, 84 for STX40 from documents dated 2012-06 to 2019-02):
   - 59 windows fully inside the issuer-covered period: rebuilt total return within **median
     0.01%, max 0.09% a year** of the stated figure. The same windows from Yahoo dividends alone:
     median 1.22%, max 2.86% a year off (the missing 2010-2012 dividends). The 21 windows that start
     2013 or later match from Yahoo alone (median 0.01%, max 0.05%), which also covers 2015-2016
     where no issuer amounts were found.
   - Windows reaching back before 2010-07: up to 0.91% a year too low, the 6 unknown quarters.
     So 2009 to mid-2010 STX40 total return is **not trustworthy** and must not be used.
   - STXPRO: 3 stated returns (2018-07 to 2021-06), median gap 0.0, max 0.52 (1 year to 2018-06).
     STXGOV: none before the holdout. Newer fact sheets show returns in a chart, not parsed.
4. **Ex-dates.** Yahoo lists most JSE dividends twice; the data check ASSUMED the later date is
   the ex-date. Tested on prices before the holdout: the return on each candidate date in units of
   the dividend yield (about -1 on the true ex-date). For pairs that cross a month end, the only
   case that changes monthly returns, the later date carries the drop: STX40 -1.22 vs +0.20
   (27 pairs, t -2.4), STXPRO -0.86 vs +0.20 (26, t -3.9), STXGOV -0.88 vs +0.11 (9, t -8.8). So
   the keep-later rule is **verified where it matters**. Caveat: for 3 same-month STX40 pairs in
   2014 the issuer's announced ex-date is the EARLIER Yahoo date, which the price test does not
   back (same-month t -1.3); same-month placement does not change monthly returns. ETFBND has
   only 3 same-month pairs (no test).

## Trusted dividend record after this check

| fund | trusted | verified by | not verified / not trusted |
|---|---|---|---|
| STX40 | 2010-07 to 2026 | issuer amounts 2010-Q3 to 2012 (used in the rebuild), issuer match 2013-2026, stated returns to 2019-02 | not trusted 2009-01 to 2010-06; 2019-2020 rests on Yahoo alone |
| STXPRO | 2017-02 to 2026 | issuer match 21/21, 3 stated returns | 2018-Q3 to 2020-Q2 and 2022-Q2 to 2023-Q3 rest on Yahoo alone |
| STXGOV | 2020-05 to 2026 | issuer match 14/14 | 2022-2023 rest on Yahoo alone |
| SYGWD, CSPROP, ETFBND | complete years in the data check | dividend counts per year only | no issuer check at all |

For the item 1 pre-registration: STX40 can start at 2010-07; the 4-class window (no bonds) can
start at 2013-01 with CSPROP until STXPRO lists (2017-02; CSPROP has 4 dividends a year
2013-2016) and SYGWD until STXWDM lists (2017-07; SYGWD 2 a year 2013-2017), but those two proxy
legs rest on dividend COUNTS, not amounts, and the pre-registration must say so; the 5-class
window is still set by the bond leg (2019-06), whose ETFBND part (to 2020-05) is unverified.
No dividend is estimated anywhere.
