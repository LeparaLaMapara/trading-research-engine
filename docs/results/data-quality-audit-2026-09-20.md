# Data quality audit — 2026-09-20

Read-only audit of `data/market.db` (`bars`) and `data/telemetry.db` (`ticks`, `latency`,
`symbol_spec`, `snapshots`). Nothing was modified. No broker connection was opened.

Row counts were taken while the tick recorder was still running, so tick totals are a
snapshot, not a final figure.

| Object | Size at audit time |
|---|---|
| `bars` total rows | 1,047,349 |
| `bars` D1 | 186,138 rows, 64 symbols, 2014-09-19 to 2026-09-19 |
| `bars` H1 | 861,211 rows, 24 symbols, 2020-09-16 to 2026-09-15 |
| `ticks` | 363,154 rows, 27 symbols |
| `latency` | 1,984 rows (one probe type, `version`) |
| `symbol_spec` | 27 rows, all captured 2026-09-20 |

Headline: the **bar database is in good shape** and internally consistent. The **tick
database is not a dataset** — it is ten hours of recording dressed up as 362,000 rows, and
the cost map already on disk was built from 58 seconds of it.

---

## Severity summary

| # | Finding | Severity |
|---|---|---|
| 1 | Tick telemetry is 10.3 hours of wall clock, 88% of it one Wednesday | SEVERE |
| 2 | Eight UTC hours have zero ticks; London and US-afternoon sessions unmeasured | SEVERE |
| 3 | `data/cost_map.csv` covers 1 of 168 hour-of-week buckets, from a 58-second run | SEVERE |
| 4 | 7.9% of ticks (41% of EURUSD) have bid exactly equal to ask | SEVERE |
| 5 | `server_ts` / `recv_latency_ms` null on 363,125 of 363,154 rows | SEVERE |
| 6 | Crypto D1 volume is a synthetic constant (1434) for whole years | SEVERE |
| 7 | XRPUSD D1 before Nov 2020 is a placeholder series (price pinned at 0.01, volume 1) | SEVERE |
| 8 | Crypto D1 weekend bars absent for 2018–2023, present before and after | SEVERE |
| 9 | Three symbols have multi-year holes: XPDUSD/XPTUSD 462 weekdays, CHINA50 375 | SEVERE |
| 10 | D1 bars are stamped at the broker day boundary, not midnight | SEVERE (trap) |
| 11 | 32.6% of ticks are one-sided updates with the other side carried forward | MODERATE |
| 12 | The universe has two different as-of dates (21 symbols 3 days behind 40) | MODERATE |
| 13 | H1 exists for only 24 of 64 symbols and is 4 days staler than D1 | MODERATE |
| 14 | Volume level-shifts of 5x to 78x mid-history on 12 symbols | MODERATE |
| 15 | EURSEK 2020-06-14: open and low are literally 0.0 | MODERATE |
| 16 | 250 non-crypto symbol-weeks contain a sixth D1 bar (DST boundary weeks) | MODERATE |
| 17 | `symbol_spec` and `swaps.json` are a single 2026-09-20 snapshot applied to 12 years | MODERATE |
| 18 | API round-trip latency median ~950 ms, p99 ~3,900 ms | MODERATE |
| 19 | 456 zero-range bars, 282 frozen (repeated OHLC) bars | COSMETIC |
| 20 | 23 non-crypto ticks stamped on a Sunday (subscription snapshot, not trading) | COSMETIC |
| 21 | `spread_pips` is not comparable across asset classes | COSMETIC |

---

## 1. Coverage

### D1

D1 bars are stamped at **21:00 UTC (summer) or 22:00 UTC (winter)** — the broker's day
boundary, not midnight. 122,368 bars sit at 21:00 and 63,770 at 22:00. A bar stamped
`2026-09-17 21:00 UTC` is the session of **18 September**. All coverage figures below use
that corrected session date. (Measuring on raw UTC dates instead produces a fake ~20.4%
"missing weekday" rate for every FX pair, because Friday's session never lands on a Friday.)

Worst coverage (session-date basis, weekday sessions only):

| symbol | bars | first | last | weekday sessions in span | missing | miss % | longest run missing | run starts |
|---|---|---|---|---|---|---|---|---|
| CHINA50 | 2,143 | 2016-06-13 | 2026-09-18 | 2,680 | 537 | 20.0% | **375** | 2016-12-26 |
| XPDUSD | 2,149 | 2016-06-22 | 2026-09-18 | 2,673 | 524 | 19.6% | **462** | 2016-06-29 |
| XPTUSD | 2,431 | 2015-05-11 | 2026-09-18 | 2,965 | 534 | 18.0% | **462** | 2016-06-29 |
| HK50 | 2,967 | 2014-09-19 | 2026-09-15 | 3,128 | 163 | 5.2% | 4 | 2021-04-01 |
| SA40 | 1,599 | 2020-04-28 | 2026-09-18 | 1,669 | 70 | 4.2% | 2 | 2021-04-02 |
| CA60 | 1,599 | 2020-04-29 | 2026-09-18 | 1,668 | 69 | 4.1% | 2 | 2020-12-25 |
| AUS200 | 3,041 | 2014-09-19 | 2026-09-15 | 3,128 | 95 | 3.0% | 3 | 2021-04-01 |
| XNGUSD | 2,586 | 2016-07-04 | 2026-09-18 | 2,665 | 79 | 3.0% | 2 | 2019-12-24 |
| UK100 | 3,050 | 2014-09-22 | 2026-09-18 | 3,130 | 82 | 2.6% | 2 | 2016-03-25 |
| US30 | 3,079 | 2014-09-22 | 2026-09-18 | 3,130 | 53 | 1.7% | 25 | 2014-09-29 |

The 28 major FX pairs are all at **19 missing weekday sessions out of 3,128–3,130 (0.61%)**,
and every one of those 19 is a genuine market holiday (25 Dec, 1 Jan, Good Friday). FX D1
coverage is excellent.

The three long holes are not holidays. **XPDUSD and XPTUSD are missing 462 consecutive
weekdays from 2016-06-29** (roughly 21 months). **CHINA50 is missing 375 consecutive
weekdays from 2016-12-26**, and its 2016/2018 prices are stored with zero decimal places.
**US30 is missing 25 consecutive weekdays from 2014-09-29.**

### H1

H1 exists for only **24 of the 64 D1 symbols**, and starts 2020-09-16, six years later than
D1. Counting only hours inside each symbol's own observed trading window (so the daily
close of an index does not count as a gap):

| symbol | bars | active UTC hours | trading days | expected slots | missing in-session | miss % |
|---|---|---|---|---|---|---|
| AUS200 | 32,685 | 22 | 1,548 | 34,056 | 2,448 | 7.19% |
| HK50 | 23,929 | 17 (01–18) | 1,470 | 24,990 | 1,078 | 4.31% |
| US500 | 35,366 | 23 | 1,557 | 35,811 | 1,457 | 4.07% |
| XTIUSD | 35,417 | 23 | 1,555 | 35,765 | 1,361 | 3.81% |
| XAUUSD | 35,434 | 23 | 1,555 | 35,765 | 1,345 | 3.76% |
| XAUEUR | 35,435 | 23 | 1,555 | 35,765 | 1,344 | 3.76% |
| the 12 FX pairs | 37,290–37,296 | 24 | 1,562 | 37,488 | 1,013–1,017 | 2.71% |
| XBRUSD | 32,756 | 21 | 1,548 | 32,508 | 797 | 2.45% |
| XAGUSD | 35,393 | 22 | 1,555 | 34,210 | 604 | 1.77% |
| DE40 | 34,679 | 22 | 1,528 | 33,616 | 575 | 1.71% |
| BTCUSD | 43,532 | 24 | 1,563 | 37,512 | 542 | 1.44% |
| ETHUSD | 43,549 | 24 | 1,563 | 37,512 | 524 | 1.40% |
| ADAUSD | 25,516 | 24 | 762 | 18,288 | 7 | 0.04% |

Counting simply "gaps longer than 4 hours that do not span a weekend", as originally asked:

| symbol | such gaps | worst gap | when |
|---|---|---|---|
| HK50 | 1,156 | 94 h | 2026-02-16 03:00 UTC (Chinese New Year) |
| XBRUSD | 245 | 31 h | 2025-12-24 18:00 |
| AUS200 | 48 | 67 h | 2024-12-24 03:00 |
| US500 | 47 | 31 h | 2025-12-24 18:00 |
| XTIUSD | 13 | 30 h | 2025-12-24 18:00 |
| XAUUSD / XAUEUR / XAGUSD | 11 each | 30 h | 2025-12-24 18:00 |
| BTCUSD | 10 | 22 h | 2021-02-10 |
| ETHUSD | 9 | 13 h | 2025-05-31 04:00 |
| DE40 | 7 | 75 h | 2024-12-23 21:00 |
| the 12 FX pairs | 5 each | 27 h | 2025-12-24 21:00 |

HK50's 1,156 gaps are overwhelmingly Hong Kong public holidays and the lunch break; they
are real market closures, not lost data. The Christmas / New Year gaps on every symbol are
also real. **But a naive 4-hour gap rule will flag 1,343 "holes" that are mostly legitimate,
so a gap-filling routine written against that rule would fabricate 9,632 hours of HK50
prices that never traded.**

### Symbols present in one place but not another

- D1 but no H1 (40 symbols): AUDCAD, AUDNZD, BCHUSD, CA60, CADJPY, CHFJPY, CHINA50, DOTUSD,
  ES35, EURCAD, EURCHF, EURNOK, EURNZD, EURSEK, EURZAR, F40, GBPAUD, GBPCAD, GBPCHF, IT40,
  JP225, LTCUSD, NZDJPY, SA40, SOLUSD, STOXX50, UK100, US2000, US30, USDMXN, USDNOK, USDPLN,
  USDSEK, USDSGD, USDZAR, USTEC, XNGUSD, XPDUSD, XPTUSD, XRPUSD.
- Ticks but no H1 bars: NZDJPY, SOLUSD, XRPUSD.
- Everything with H1 bars also has ticks and D1.

---

## 2. Duplicates

**Clean.** Zero duplicate `(symbol, period, ts_utc)` rows — the primary key enforces it.
Zero cases of two D1 bars mapping to the same session date.

Frozen bars (a bar whose O, H, L and C all equal the previous bar's) — 282 in total across
11 of the 88 symbol/period combinations:

| symbol | period | bars | frozen | % | longest run | first |
|---|---|---|---|---|---|---|
| XRPUSD | D1 | 3,329 | 246 | 7.39% | **228** | 2016-05-16 |
| HK50 | D1 | 2,967 | 7 | 0.24% | 2 | 2014-10-01 |
| STOXX50 | D1 | 3,061 | 6 | 0.20% | 2 | 2014-12-24 |
| IT40 | D1 | 3,055 | 6 | 0.20% | 2 | 2014-12-24 |
| US500 | H1 | 35,366 | 4 | 0.01% | 4 | 2025-11-28 06:00 |
| DE40 | D1 | 3,062 | 4 | 0.13% | 1 | 2014-12-24 |
| AUS200 | D1 / H1 | — | 2 / 2 | — | 1 | 2014-12-25 / 2023-07-05 |
| ES35 | D1 | 3,076 | 2 | 0.07% | 1 | 2014-12-25 |
| XTIUSD | H1 | 35,417 | 2 | 0.01% | 2 | 2025-11-28 04:00 |
| UK100 | D1 | 3,050 | 1 | 0.03% | 1 | 2015-12-27 |

Outside XRPUSD this is trivial — Christmas Eve half-days and the US Thanksgiving Friday
(2025-11-28) on US500 and XTIUSD. XRPUSD is a separate problem, see finding 7.

---

## 3. Bad bars

| Check | Count |
|---|---|
| `high < low` | **0** |
| `close` outside `[low, high]` | **0** |
| `open` outside `[low, high]` | **0** |
| null OHLC | **0** |
| null / zero / negative volume | **0** |
| zero or negative price | **1** |
| zero-range bars (`high == low`) | 456 |

The one bad price: **EURSEK D1, 2020-06-14 21:00 UTC — `open = 0.0`, `low = 0.0`**, while
`high = 10.58283` and `close = 10.50565`. Neighbouring days are all near 10.5. The bar's
measured range is 100.73% of its close, 54.8 sigma — the single largest range outlier in the
whole database.

Zero-range bars concentrate in XRPUSD D1 (248), HK50 D1 (20), DE40 H1 (19), HK50 H1 (18),
AUS200 D1 (16), STOXX50 D1 (15), IT40 D1 (14). Outside XRPUSD these are holiday half-days.

### Returns beyond 10 sigma

331 close-to-close returns exceed 10 sigma of their own symbol/period history (47 on D1,
284 on H1). Worst 15 by sigma:

| symbol | period | timestamp (UTC) | prev close | close | move | sigma |
|---|---|---|---|---|---|---|
| EURCHF | D1 | 2015-01-14 22:00 | 1.20090 | 0.97401 | −18.89% | −41.8 |
| ADAUSD | H1 | 2025-10-11 00:00 | 0.75835 | 0.50785 | −33.03% | −39.5 |
| GBPUSD | H1 | 2022-09-26 00:00 | 1.07930 | 1.04017 | −3.63% | −33.5 |
| EURGBP | H1 | 2022-09-26 00:00 | 0.89738 | 0.92032 | +2.56% | +33.4 |
| ETHUSD | H1 | 2021-01-03 22:00 | 735.28 | 988.80 | +34.48% | +33.3 |
| USDCHF | D1 | 2015-01-14 22:00 | 1.01870 | 0.83801 | −17.74% | −31.9 |
| XAGUSD | H1 | 2026-02-05 02:00 | 86.673 | 74.416 | −14.14% | −31.5 |
| GBPCHF | D1 | 2015-01-14 22:00 | 1.55198 | 1.27250 | −18.01% | −30.8 |
| CHFJPY | D1 | 2015-01-14 22:00 | 115.179 | 138.296 | +20.07% | +30.0 |
| DE40 | H1 | 2025-04-09 17:00 | 19,753.90 | 21,132.70 | +6.98% | +29.8 |
| US500 | H1 | 2025-04-09 17:00 | 5,026.05 | 5,367.00 | +6.78% | +29.8 |
| XTIUSD | H1 | 2026-03-08 22:00 | 91.36 | 106.96 | +17.08% | +29.1 |
| XBRUSD | H1 | 2026-03-08 23:00 | 93.14 | 108.40 | +16.38% | +29.0 |
| ADAUSD | H1 | 2025-03-02 17:00 | 0.64585 | 0.86305 | +33.63% | +28.6 |
| GBPJPY | H1 | 2022-09-26 00:00 | 154.905 | 149.532 | −3.47% | −28.4 |

**Almost all of these are real events, not corruption** — the SNB franc de-peg (2015-01-15),
the UK mini-budget (2022-09-26), the April 2025 tariff reversal, the April 2020 oil
collapse (XTIUSD D1 2020-04-20, −53.47%, −23.6 sigma). The only clearly artificial entries
are XRPUSD D1 2017-03-30 (+100.00%, 0.01 → 0.02) and 2017-05-07 (+111.11%, 0.09 → 0.19),
which are rounding steps in a two-decimal price, not price moves. See finding 7.

Open-to-previous-close jumps greater than 5% on D1 FX: **none**. The series are continuous.

---

## 4. Stale quotes in ticks

Consecutive ticks with **identical bid and identical ask**: only **247 of 363,154 (0.07%)**.
Measured inside each recording session (so the multi-day recorder outages do not create
false runs):

| symbol | ticks | stale repeats | longest run | duration | ended |
|---|---|---|---|---|---|
| XAUUSD | 93,657 | 69 | **19 ticks** | **1,681 s (28 min)** | 2026-09-15 22:00:14 UTC |
| US500 | 1,187 | 1 | 2 | 57 s | 2026-09-20 09:33:09 |
| EURUSD | 18,496 | 14 | 2 | 8.4 s | 2026-09-16 01:54:32 |
| NZDUSD | 21,144 | 15 | 2 | 7.9 s | 2026-09-16 02:58:10 |
| GBPUSD | 32,381 | 59 | 2 | 6.8 s | 2026-09-15 23:35:04 |
| every other symbol | — | ≤ 13 | 2 | ≤ 6.2 s | — |

The XAUUSD 28-minute freeze sits squarely in gold's daily 21:00–22:00 UTC settlement break —
the recorder kept writing rows during a closed market. That is the only stale run of any
consequence. **Tick-level staleness is a non-problem.** The real quote problems are 4 and 11
below, which are different failure modes entirely.

---

## 5. Timestamps

All clean:

| Check | Result |
|---|---|
| `ts_utc` monotonic per symbol (in insertion order) | **Yes — zero backwards steps, all 27 symbols** |
| `ts_utc` monotonic globally by `id` | **Yes — zero backwards steps** |
| Duplicate `(symbol, ts_utc)` | **0** |
| Duplicate `ts_utc` across any symbol | **0** (363,154 distinct values for 363,154 rows) |
| Exact duplicate `(ts_utc, symbol, bid, ask, side)` | **0** |
| `ts_sast` vs `ts_utc` converted to UTC+2, 200 random rows | max absolute difference **1.18e-07 s**, zero mismatches |
| Stated offset in `ts_sast` | `+02:00` on all 363,154 rows (SAST has no DST — correct) |
| `dow_sast`, `hour_sast`, `hour_of_week` vs `ts_sast` | **0 mismatches each, full table** |
| Rows where `server_ts` is after local receive (negative latency) | **0** |

The timestamp layer is the best-engineered part of this system. The smallest inter-tick
interval is 55 microseconds (AUDUSD), which is fine.

### But: `server_ts` and `recv_latency_ms` are almost entirely null

**363,125 of 363,154 rows (99.992%) have null `server_ts` and null `recv_latency_ms`.** Only
**29 rows** carry values, all written on 2026-09-20 — the columns were added to the table by
`ALTER TABLE` after nearly all the data was recorded.

Of those 29, **22 show `recv_latency_ms` around 131,712,600 ms — 36.6 hours.** That is not
latency. It is the first spot event after subscription, carrying the broker's last-trade
timestamp from the previous Friday close, differenced against a Sunday receive time. Filter
those out at the 60,000 ms threshold and **seven rows remain**:

| statistic | recv_latency_ms |
|---|---|
| n | **7** |
| min | 51.4 |
| median | 260.8 |
| p90 | 2,443.8 |
| p95 | 3,320.2 |
| p99 | 4,021.3 |
| max | 4,196.6 |

Seven observations, four symbols, one minute of wall clock. This is not a latency
distribution; it is an anecdote.

The separate `latency` table (API round-trip probe) is more usable — 1,984 rows — and says
something uncomfortable:

| date | n | median rtt | p90 | p99 | max |
|---|---|---|---|---|---|
| 2026-08-06 | 2 | 1,028.8 ms | — | — | 1,065.1 ms |
| 2026-09-15 | 285 | 961.5 ms | 1,167.1 ms | 3,840.7 ms | 4,840.0 ms |
| 2026-09-16 | 1,677 | 941.8 ms | 1,101.7 ms | 3,490.0 ms | 4,940.6 ms |
| 2026-09-20 | 20 | 953.9 ms | 1,525.2 ms | 2,221.4 ms | 2,351.6 ms |

**Median round trip to the broker API is roughly 950 ms, with a p99 near 3.9 seconds.**

---

## 6. Spread sanity

Per symbol, from `spread_pips`:

| symbol | n | min | median | p99 | max | max ÷ median | ticks with spread = 0 |
|---|---|---|---|---|---|---|---|
| NZDUSD | 21,144 | 0.0 | 0.1 | 16.4 | 18.2 | **182.0** | 4,414 (20.9%) |
| USDJPY | 38,930 | 0.0 | 0.1 | 6.2 | 12.0 | **120.0** | 8,010 (20.6%) |
| EURUSD | 18,496 | 0.0 | 0.1 | 5.3 | 10.9 | **109.0** | 7,576 (41.0%) |
| NZDJPY | 42,396 | 0.0 | 0.4 | 28.2 | 33.1 | **82.8** | 55 (0.1%) |
| AUDUSD | 22,077 | 0.0 | 0.1 | 0.3 | 6.9 | **69.0** | 7,830 (35.5%) |
| AUDJPY | 45,728 | 0.0 | 0.3 | 11.7 | 19.0 | **63.3** | 116 (0.3%) |
| GBPUSD | 32,381 | 0.0 | 0.2 | 5.5 | 12.0 | **60.0** | 401 (1.2%) |
| USDCHF | 1,444 | 0.0 | 0.1 | 0.1 | 1.8 | 18.0 | 299 (20.7%) |
| XAUUSD | 93,657 | 5.0 | 9.0 | 12.0 | 118.0 | 13.1 | 0 |
| EURAUD | 2,479 | 0.0 | 0.5 | 0.6 | 6.3 | 12.6 | 5 |
| XAUEUR | 6,315 | 5.0 | 11.0 | 16.0 | 137.0 | 12.5 | 0 |
| USDCAD | 1,658 | 0.1 | 0.2 | 0.3 | 2.5 | 12.5 | 0 |
| GBPJPY | 3,632 | 0.3 | 0.8 | 1.1 | 6.3 | 7.9 | 0 |
| DE40 | 2,287 | 5.0 | 5.0 | 23.0 | 23.0 | 4.6 | 0 |
| EURJPY | 2,497 | 0.2 | 0.9 | 0.9 | 3.8 | 4.2 | 0 |
| EURGBP | 1,294 | 0.1 | 0.3 | 0.4 | 1.2 | 4.0 | 0 |
| BTCUSD | 7,802 | 500.0 | 500.0 | 1,250.0 | 1,899.0 | 3.8 | 0 |
| XAGUSD | 4,048 | 0.8 | 1.4 | 1.5 | 3.5 | 2.5 | 0 |
| US500 | 1,187 | 3.0 | 3.0 | 3.0 | 5.0 | 1.7 | 0 |
| XRPUSD | 251 | 1.0 | 3.0 | 4.5 | 5.0 | 1.7 | 0 |
| ETHUSD | 5,516 | 290.0 | 296.0 | 296.0 | 411.0 | 1.4 | 0 |
| SOLUSD | 181 | 1,120.0 | 1,420.0 | 1,720.0 | 1,720.0 | 1.2 | 0 |
| ADAUSD | 391 | 270.0 | 270.0 | 290.0 | 300.0 | 1.1 | 0 |
| AUS200 | 422 | 12.0 | 12.0 | 12.0 | 12.0 | 1.0 | 0 |
| HK50 | 1,655 | 90.0 | 90.0 | 90.0 | 90.0 | 1.0 | 0 |
| XBRUSD | 2,578 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 |
| XTIUSD | 2,708 | 2.0 | 2.0 | 2.0 | 2.0 | 1.0 | 0 |

**Seven symbols exceed the 50x threshold: NZDUSD (182x), USDJPY (120x), EURUSD (109x),
NZDJPY (82.8x), AUDUSD (69x), AUDJPY (63.3x), GBPUSD (60x).**

The ratio is inflated at both ends. At the top, every single one of those maxima occurs
between **21:50 and 21:59 UTC on 2026-09-15** — the daily rollover, when the broker widens
quotes. Spread by UTC hour for EURUSD makes it plain:

| UTC hour | ticks | median spread (pips) | max |
|---|---|---|---|
| 0–7 | 1,126–2,680 each | 0.0–0.1 | 0.4–0.7 |
| **21** | **653** | **4.9** | **10.9** |
| 22 | 810 | 0.1 | 0.6 |
| 23 | 1,040 | 0.1 | 0.5 |

That is real broker behaviour, correctly captured. The problem is the denominator, not the
numerator — see the next finding.

**No crossed books.** Zero rows have `bid > ask`, zero negative spreads. `spread_pips` and
`spread_price` reproduce exactly from `bid_raw`/`ask_raw` (max mismatch 0.0), and
`bid == bid_raw / 1e5` on every row, so the fixed 1e5 price scale documented in
`telemetry/units.py` is applied consistently. Cross-checking tick mid-price against the last
D1 close for all 27 symbols gives ratios between 0.86 and 1.02, all explainable by six weeks
of price movement — **there is no scale error**.

### The zero-spread problem

**28,706 ticks (7.9%) have `bid_raw` exactly equal to `ask_raw`.** By symbol share:
EURUSD 41.0%, AUDUSD 35.5%, NZDUSD 20.9%, USDCHF 20.7%, USDJPY 20.6%.

This is not only the one-sided-update artefact. For EURUSD, 31.8% of *two-sided* (`bid+ask`)
updates also show a zero spread. Longest genuinely contiguous run (consecutive ticks less
than 60 seconds apart): EURUSD 15 ticks over 33 s, USDJPY 22 ticks over 53 s.

Whatever the cause, **the median recorded spread for EURUSD, AUDUSD, NZDUSD, USDCHF and
USDJPY is 0.0 to 0.1 pips.** Commission is not in this table at all — `swaps.json` records
`commission: 3000` for EURUSD, which never reaches `ticks`. A cost model built from these
columns will conclude that trading EURUSD is close to free.

---

## 7. Weekend and closure activity

### Ticks

**1,752 ticks fall on a Saturday or Sunday UTC — every one of them on Sunday 2026-09-20**,
between 09:32 and 10:23 UTC. Of those, 1,729 are crypto (BTCUSD 783, ETHUSD 506, XRPUSD 251,
SOLUSD 181, ADAUSD 8), which trade at weekends and are legitimate.

The remaining **23 are FX, metals, indices and energy on a closed market**: one tick each for
AUDJPY, AUDUSD, AUS200, DE40, EURAUD, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, HK50, NZDJPY,
NZDUSD, USDCAD, USDCHF, USDJPY, XAGUSD, XAUEUR, XAUUSD, XBRUSD, XTIUSD, and two for US500.
All 23 share the timestamp 2026-09-20 09:32:12 to within 300 milliseconds — they are the
broker's one-shot snapshot on subscription, not live quotes. Their spreads are the stale
Friday-close values: XAUEUR 137 pips, HK50 90, XAUUSD 40, AUS200 12.

Harmless in themselves, **fatal if pooled into a spread distribution**: XAUEUR's 137-pip
maximum and XAUUSD's 118-pip maximum come from exactly this kind of closed-market row.

### Bars

**253 D1 bars on 48 non-crypto symbols carry a Saturday or Sunday session date.** They
cluster on seven specific weekends: 2015-03-15 (45 symbols), 2015-03-08 (43), 2014-11-08
(34), 2017-11-05 (32), 2015-11-01 (30), 2015-11-08 (29), 2016-11-06 (27). These are US
daylight-saving transition weekends. The bars are 24 hours wide but nearly empty — EURUSD's
2014-11-07 22:00 bar has volume 1,544 against a weekday median near 190,000.

Consequence: **250 non-crypto symbol-weeks contain six D1 bars instead of five.** A
weekly-resampling or "5 bars = 1 week" assumption is wrong on those weeks. The behaviour
stops after 2017; there are only three such bars after 2018 (2023-09-23, 2023-09-30,
2014-10-25 era aside).

Non-crypto H1 weekend bars (443–821 per symbol) are the Sunday 21:00–23:00 UTC market open
and are correct.

### Crypto weekends are missing for five years

This is the serious one. Fraction of expected weekend D1 bars actually present:

| symbol | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSD | 0.61 | **0.00** | **0.00** | **0.00** | 0.03 | **0.00** | **0.00** | 0.79 | 1.00 | 1.00 |
| ETHUSD | 0.05 | **0.00** | **0.00** | **0.00** | 0.04 | **0.00** | **0.00** | 0.79 | 1.00 | 1.00 |
| LTCUSD | 0.05 | **0.00** | **0.00** | **0.00** | 0.04 | **0.00** | **0.00** | 0.79 | 1.00 | 0.99 |
| BCHUSD | 0.05 | **0.00** | **0.00** | **0.00** | 0.04 | **0.00** | **0.00** | 0.79 | 1.00 | 0.99 |
| XRPUSD | 0.00 | **0.00** | **0.00** | 0.49 | 0.98 | 1.01 | 1.01 | 0.99 | 1.00 | 0.99 |
| ADAUSD | — | — | — | — | — | — | 1.00 | 0.99 | 1.00 | 0.99 |
| DOTUSD | — | — | — | — | 0.86 | 0.89 | 1.01 | 0.99 | 1.00 | 0.99 |
| SOLUSD | — | — | — | — | — | 0.80 | 1.01 | 0.99 | 1.00 | 1.00 |

BTCUSD had full weekend coverage in 2014–2016, lost it entirely from 2018 to 2023, and
regained it in 2024. **The meaning of "one D1 bar" for BTCUSD changes twice inside the
sample.** Before 2017 and after mid-2024 a Monday bar is one calendar day; between 2018 and
2023 a Monday bar silently absorbs the Saturday and Sunday move. Any volatility estimate,
any per-bar return distribution, any weekend-effect study computed across that boundary is
comparing two different things.

---

## 8. Everything else that would silently corrupt a backtest

### 8.1 The tick database is ten hours long — SEVERE

362,000 rows sounds like a dataset. It is not. Distribution by calendar day:

| date | day | ticks | share | symbols | window (UTC) |
|---|---|---|---|---|---|
| 2026-08-06 | Thursday | 969 | 0.3% | 8 | 16:03:28 → 16:04:26 (58 seconds) |
| 2026-09-15 | Tuesday | 41,349 | 11.4% | 8 | 21:32:13 → 23:59:59 |
| 2026-09-16 | Wednesday | 319,084 | **87.9%** | 25 | 00:00:00 → 15:13:10 |
| 2026-09-20 | Sunday | 1,752 | 0.5% | 27 | 09:32:12 → 10:23:24 |

The span from first tick to last is 1,074.3 hours. **1,064.0 of those hours are recorder
downtime. Total actual recording is 10.3 hours.** There are four outages longer than a
minute: 40 days (Aug 6 → Sep 15), 3.8 days (Sep 16 → Sep 20), 7.4 hours (Sep 16 07:23 →
14:48), and 45 minutes (Sep 20).

Nearly 88% of the sample is one Wednesday. Whatever this measures, it is the microstructure
of 16 September 2026, not of the market.

### 8.2 Eight UTC hours have zero ticks — SEVERE

| UTC hour | ticks | symbols |
|---|---|---|
| 0 | 39,685 | 8 |
| 1 | 37,707 | 8 |
| 2 | 35,452 | 8 |
| 3 | 31,597 | 8 |
| 4 | 22,520 | 8 |
| 5 | 26,992 | 8 |
| 6 | 40,585 | 8 |
| 7 | 17,794 | 8 |
| **8** | **0** | 0 |
| 9 | 281 | 25 |
| 10 | 1,471 | 4 |
| **11, 12, 13** | **0** | 0 |
| 14 | 27,459 | 25 |
| 15 | 39,293 | 25 |
| 16 | 969 | 8 |
| **17, 18, 19, 20** | **0** | 0 |
| 21 | 4,172 | 8 |
| 22 | 16,331 | 8 |
| 23 | 20,846 | 8 |

**Hours 8, 11, 12, 13, 17, 18, 19 and 20 UTC contain no ticks at all.** That removes the
London morning, the London/New York overlap and the New York afternoon — the deepest, most
liquid and cheapest hours of the FX day. What survives is the Asian session and the rollover.

Per symbol it is worse. Counting UTC hours with at least 50 ticks:

| symbol | ticks | hours with ≥50 ticks | which hours |
|---|---|---|---|
| XRPUSD, SOLUSD | 251, 181 | **1** | 10 |
| ADAUSD, AUS200, HK50, GBPJPY, EURAUD, DE40, USDCHF, XBRUSD, XAUEUR, XAGUSD, US500, USDCAD, EURJPY, EURGBP, XTIUSD | 391–6,315 | **2** | 14, 15 |
| BTCUSD, ETHUSD | 7,802, 5,516 | 4 | 9, 10, 14, 15 |
| USDJPY | 38,930 | 13 | 0–7, 14, 15, 21–23 |
| XAUUSD | 93,657 | 13 | 0–7, 14–16, 22, 23 |
| AUDJPY, AUDUSD, EURUSD, NZDUSD, NZDJPY, GBPUSD | 18,496–45,728 | 14 | 0–7, 14–16, 21–23 |

**For 19 of the 27 symbols the entire record is two UTC hours or fewer.**

### 8.3 `data/cost_map.csv` is built from 58 seconds — SEVERE

The cost map already on disk contains 8 rows, all for `hour_of_week = 90` (Thursday 18:00
SAST), with tick counts of 43 to 292. Those come from the 2026-08-06 run, which lasted 58
seconds.

| symbol | median_spread_pips | tick_count |
|---|---|---|
| AUDJPY | 0.4 | 125 |
| AUDUSD | 0.1 | 109 |
| EURUSD | 0.1 | 78 |
| GBPUSD | 0.2 | 135 |
| NZDJPY | 0.4 | 102 |
| NZDUSD | 0.1 | 85 |
| USDJPY | 0.2 | 43 |
| XAUUSD | 10.0 | 292 |

**One of 168 hour-of-week buckets, eight of 64 symbols, no commission, no slippage, no
rejection.** Any backtest that reads this file is costing trades at 0.1 pips.

### 8.4 One-sided updates carry the opposite side forward — MODERATE

`telemetry/logger.py` keeps the last known bid and ask in `self.last` and writes a row
whenever either side moves, labelling it in `side`. **118,371 of 363,154 rows (32.6%) are
one-sided**: 62,907 `ask` only, 55,464 `bid` only, versus 244,783 `bid+ask`.

On those rows the spread is computed between a fresh quote and a stale one. The staleness is
usually sub-second, so the effect is small, but it is systematically biased: a one-sided
improvement narrows the recorded spread, and the zero-spread rows cluster in exactly these
rows (EURUSD: 48.6% of `ask`-only rows and 43.8% of `bid`-only rows show a zero spread,
versus 31.8% of two-sided rows).

### 8.5 The universe has two as-of dates — MODERATE

D1 last bars:

| last D1 bar (UTC stamp) | session | symbols |
|---|---|---|
| 2026-09-14 21:00 | 2026-09-15 | **21** (the 21 that also have H1) |
| 2026-09-17 21:00 | 2026-09-18 | **40** |
| 2026-09-18 21:00 | 2026-09-19 | 3 (BTCUSD, ETHUSD, SOLUSD) |

H1 last bar is 2026-09-15 for all 24 H1 symbols — **four days staler than the D1 it is
supposed to refine.**

A cross-sectional strategy that rebalances "on the last available bar" is putting EURUSD's
15 September next to USDZAR's 18 September and BTCUSD's 19 September. That is a three-day
look-ahead for part of the universe, in a ranking model, for free.

### 8.6 Volume is not a consistent series — MODERATE

Twelve symbols show a year-on-year median volume shift of 5x or more:

| symbol | from | to | median before | median after | ratio |
|---|---|---|---|---|---|
| XRPUSD | 2025 | 2026 | 1,434 | 111,719 | **77.9** |
| SOLUSD | 2025 | 2026 | 1,434 | 79,834 | **55.7** |
| XRPUSD | 2020 | 2021 | 24 | 1,433 | 59.7 |
| XRPUSD | 2019 | 2020 | 1 | 24 | 24.0 |
| ADAUSD | 2025 | 2026 | 1,439 | 15,667 | 10.9 |
| CHINA50 | 2016 | 2018 | 3,489 | 26,700 | 7.7 |
| HK50 | 2017 | 2018 | 25,580 | 175,590 | 6.9 |
| BCHUSD | 2023 | 2024 | 19,026 | 125,632 | 6.6 |
| AUS200 | 2017 | 2018 | 4,023 | 26,523 | 6.6 |
| DOTUSD | 2025 | 2026 | 1,439 | 9,482 | 6.6 |
| US500 | 2017 | 2018 | 5,595 | 34,924 | 6.2 |
| JP225 | 2017 | 2018 | 7,347 | 37,900 | 5.2 |
| STOXX50 | 2017 | 2018 | 2,423 | 12,539 | 5.2 |
| ETHUSD | 2018 | 2019 | 13,808 | 69,396 | 5.0 |

Worse, four crypto symbols have a **synthetic volume plateau**. Twelve symbol-years have
fewer than 20% distinct volume values:

| symbol | year | bars | distinct volumes | median |
|---|---|---|---|---|
| SOLUSD | 2024 | 366 | 43 (1,434 appears 296 times) | 1,434 |
| SOLUSD | 2023 | 365 | 61 | 1,434 |
| SOLUSD | 2022 | 272 | 47 | 1,434 |
| DOTUSD | 2022 | 349 | 68 | 1,434 |
| XRPUSD | 2024 | 366 | 46 (1,434 appears 252 times) | 1,434 |
| XRPUSD | 2021, 2022 | 361, 365 | 67, 68 | 1,433 |
| XRPUSD | 2016–2019 | 165–260 | **1** | **1** |
| XRPUSD | 2020 | 302 | 24 | 24 |

1,434 is suspiciously close to 1,440 minutes in a day. **This is a count of minute buckets,
capped, not traded volume.** Any volume-weighted or liquidity-filtered feature on crypto
before 2026 is reading a constant.

### 8.7 XRPUSD before November 2020 is a placeholder — SEVERE

| year | bars | min close | max close | bars at ≤ 0.011 | decimals | median volume |
|---|---|---|---|---|---|---|
| 2016 | 165 | 0.0100 | 0.0100 | **165 (all)** | 2 | 1 |
| 2017 | 260 | 0.0100 | 1.8700 | 64 | 2 | 1 |
| 2018 | 260 | 0.2335 | 2.6900 | 0 | 4 | 1 |
| 2019 | 259 | 0.1754 | 0.4634 | 0 | 4 | 1 |
| 2020 | 302 | 0.1353 | 0.7247 | 0 | 4 | 24 |
| 2021+ | 361–366 | — | — | 0 | 4 | 1,433+ |

Every 2016 bar closes at exactly 0.01. 228 consecutive D1 bars are byte-identical
(O=H=L=C=0.01, volume 1). Precision improves from 2 decimals to 4 in 2018, and volume stops
being 1 only in late 2020. The 2017-03-30 "+100% day" and the 2017-05-07 "+111% day" that
appear as 10-sigma events are rounding steps in a two-decimal field, not price moves.
**988 XRPUSD D1 bars carry volume 1**, spanning 2016-05-16 to 2020-11-07.

### 8.8 Bar history is internally consistent — the one clean bill of health

Aggregating H1 bars up to each D1 session and comparing to the stored D1 bar, across
**37,095 symbol-days on the 24 overlapping symbols**:

| Check | Result |
|---|---|
| Session open mismatch > 5 bp | **0** |
| Session close mismatch > 5 bp | **4** (ETHUSD 1, USDCHF 1, NZDUSD 1, GBPJPY 1) |
| D1 high below the H1-derived high | **0** |
| D1 low above the H1-derived low | 2 |
| Median volume ratio (summed H1 ÷ D1) | **1.000 on all 24 symbols** |
| Median open error | 0.00 bp |
| Median close error | 0.00 bp |

D1 and H1 agree to the tick. Whatever else is wrong, the two bar series are not telling
different stories, and the broker day boundary is applied consistently across both.

### 8.9 Symbol specs and swaps are a single snapshot — MODERATE

`symbol_spec` has 27 rows, all with `captured_ts = 1789897…` (2026-09-20). `swaps.json`
likewise captures a single 2026-09-20 reading (EURUSD swapLong −0.83, swapShort +0.15,
commission 3000). **These point-in-time values are the only financing and commission numbers
available, and they are being applied to twelve years of history.** Swap rates track policy
rates; EURUSD carry in 2015 was not EURUSD carry in 2026. The existing
`carry-2026-09-19-assumed-financing.json` naming suggests this is already understood — it
should stay understood.

### 8.10 `spread_pips` is not a common unit — COSMETIC

`pip_position` ranges from 1 (indices) to 5 (ADAUSD). A "pip" is 10 index points on US500,
0.01 on XAUUSD, and 0.00001 on ADAUSD. BTCUSD's median spread of 500 "pips" is $5.00; HK50's
constant 90 "pips" is 9 index points. **Averaging or ranking `spread_pips` across asset
classes produces nonsense.** Convert to basis points of price before any cross-symbol
comparison.

### 8.11 Constant spreads on six symbols — COSMETIC

AUS200 (12.0), HK50 (90.0), XBRUSD (1.0), XTIUSD (2.0), US500 (min 3.0, max 5.0) and
ADAUSD (min 270, max 300) show effectively a single spread value throughout. Given
that most of those symbols were only recorded during UTC hours 14–15, this is more likely
thin sampling than a fixed markup — but it means those symbols have **no measured spread
variability at all**, and a cost model will treat them as having zero cost uncertainty.

---

## What a researcher must not do with this data

1. **Do not build a cost model, a slippage estimate or an execution assumption from
   `ticks` or from `data/cost_map.csv`.** The tick table is 10.3 hours long, 88% of it one
   Wednesday, with eight UTC hours entirely absent — including every deep-liquidity hour. The
   cost map covers one of 168 hour-of-week buckets from a 58-second recording. It says EURUSD
   costs 0.1 pips. It does not know that.

2. **Do not quote a latency number.** `recv_latency_ms` exists on 29 of 363,154 rows, 22 of
   which are a 36-hour subscription artefact. Seven usable observations. If a latency figure
   is needed, use the `latency` table (n = 1,984, median ~950 ms round trip) and say which
   table it came from.

3. **Do not treat a D1 timestamp as a calendar date.** Bars are stamped 21:00 or 22:00 UTC
   at the broker day boundary. `2026-09-17 21:00 UTC` is the 18 September session. Joining
   D1 bars to any external daily series on the naive UTC date introduces a one-day
   misalignment, which in a signal-to-return join is a one-day look-ahead.

4. **Do not run a crypto backtest across the 2018–2023 weekend hole without stating it.**
   BTCUSD, ETHUSD, LTCUSD and BCHUSD have zero weekend D1 bars from 2018 through 2023, full
   coverage before 2017 and after mid-2024. A "daily" bar means different things in different
   parts of the same series.

5. **Do not use volume on crypto before 2026, or on XRPUSD before November 2020.** Volume is
   pinned at 1,434 (a minute count) for whole symbol-years, and at exactly 1 for 988 XRPUSD
   bars. Volume-weighted features, liquidity filters and turnover constraints are reading a
   constant.

6. **Do not use XRPUSD D1 before 2018 at all.** Every 2016 close is 0.01; 228 consecutive
   bars are identical. Its 10-sigma "returns" are rounding steps.

7. **Do not rebalance a cross-sectional strategy "on the last available bar".** 21 symbols
   end on the 15 September session, 40 on the 18th, 3 on the 19th, and all H1 on the 15th.
   Pin an explicit as-of date and truncate every symbol to it.

8. **Do not gap-fill H1 from a blanket "gap > 4 hours" rule.** 1,343 such gaps exist and
   most are real closures — Hong Kong holidays alone account for 9,632 HK50 hours. Filling
   them invents prices.

9. **Do not assume five D1 bars per week.** 250 non-crypto symbol-weeks (concentrated in the
   2014–2017 DST transition weekends) contain six, and the extra one has roughly 1% of normal
   volume.

10. **Do not compare or average `spread_pips` across asset classes,** and do not pool the
    2026-09-20 Sunday snapshot rows into any spread distribution — those 23 rows carry stale
    Friday-close spreads (XAUEUR 137 pips, XAUUSD 118 pips) and are the source of several
    symbols' maxima.

11. **Do not trust XPDUSD, XPTUSD or CHINA50 across their outages.** 462, 462 and 375
    consecutive missing weekdays respectively. A return series computed straight through
    those holes joins 2016 to 2018 as if it were one day.

12. **Do not use EURSEK 2020-06-14.** `open = 0.0`, `low = 0.0`.

---

## What is actually sound

Worth saying plainly, because the failures above are loud:

- Zero duplicate keys, zero `high < low`, zero prices outside their own bar, zero null OHLC,
  zero negative or null volume in 1,047,349 bars.
- D1 and H1 reconcile to the tick over 37,095 symbol-days — volume ratio exactly 1.000.
- Timestamps are monotonic, unique to the microsecond, and `ts_sast` agrees with `ts_utc`
  to 1.18e-07 seconds with zero mismatches in `dow_sast`, `hour_sast` or `hour_of_week`.
- No crossed books, no negative latencies, no price-scale error — the fixed 1e5 scale is
  applied correctly on all 363,154 tick rows and all 27 symbols.
- The 28 major FX pairs have 0.61% missing D1 sessions over twelve years, and every one of
  those is a real market holiday.
- The 10-sigma return list is dominated by genuine market events (SNB 2015, the 2022 UK
  mini-budget, April 2020 oil, April 2025 tariffs), not by data errors.

The bar database is fit for research once the traps above are respected. The tick database
is fit for nothing yet except proving the recorder works.
