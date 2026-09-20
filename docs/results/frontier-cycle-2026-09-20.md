# Research cycle, 20 September 2026: corrections that changed the numbers

Run under the Frontier Market Intelligence brief. Four workstreams: two delegated agents (data
quality, precursor literature), two run here (clock discipline, edge-decay brackets). Every
result below is a correction to something previously believed, which is the point.

## 1. Our clock was wrong, so yesterday's latency figures were wrong

Section 12 of the brief forbids subtracting timestamps from unsynchronised clocks. We had been
doing exactly that. Measured against three NTP servers, this machine runs **86 ms behind true
time, with 58 ms of uncertainty**.

| | reported yesterday | corrected |
|---|---|---|
| BTCUSD market data latency | 216 ms | **302 ms** |
| ETHUSD | 285 ms | **371 ms** |

`lab/clock.py` now measures the offset, stores every sample in `clock_samples` so drift is
visible over time, and refuses to report any latency smaller than the clock's own uncertainty.

## 2. The threshold was a point where the data only supports an interval

Section 15. Yesterday's "threshold = 12 hours" was the last bucket tested before the curve went
negative, not the crossing. With adaptive bisection, spending extra runs only where the curve
transitions:

**ma_trend on EURUSD: the edge crosses zero between 18 and 20 hours of delay** (18 h still
positive, 20 h negative), narrowed to the data's one-hour resolution limit. The conservative
operating target is 4.5 hours, against a measured order path of about one second.

`crossing_bracket` now returns `bracketed`, `censored_right` (positive everywhere tested, so
the grid ran out before the strategy did) or `no_edge`, and the operating target is taken from
the pessimistic end.

## 3. Measured costs were too kind, and fixing them made every result worse

The data-quality audit found the tick recorder has run for **10.3 hours in total**, 87.9% of it
on a single day, and almost entirely inside 14:00-15:00 UTC, which is the London and New York
overlap and therefore the cheapest hour of the day. It also found **7.9% of ticks have bid
exactly equal to ask** and **32.6% update one side only**, with the stale side carried forward.

`measured_cost` now admits only two-sided quotes with a positive spread, requires 200 of them,
and where a symbol's spread was observed in fewer than eight distinct hours of the week it
prices at the **75th percentile instead of the median**.

| instrument | round-trip cost before | after |
|---|---|---|
| EURUSD | 0.39 bps | **1.35 bps** |
| USDJPY | 0.38 bps | **1.35 bps** |
| XAUUSD | 0.45 bps | **1.85 bps** |
| BTCUSD | 0.66 bps | **7.85 bps** |

Re-scored, every candidate is worse and the ordering is unchanged:

| model | dev Sharpe before | after |
|---|---|---|
| long_risk_parity (baseline) | 0.457 | 0.447 |
| gru_seq (previous champion) | 0.188 | 0.132 |
| rel_xgb_shallow_s30 (best follow-up) | 0.097 | 0.076 |
| xgb_shallow | -0.225 | -0.320 |

**The 19 September conclusion survives its own correction and is strengthened: nothing here
beats holding everything long, and the gap to the cost floor is wider than we thought.**

## 4. A reproducibility bug, caught by the correction

Re-running with new costs crashed on a length mismatch: the forecast cache was keyed by model
name only, and four crypto symbols had been refetched, changing the panel by twelve rows. The
cache is now keyed by the data version, so a stale cache can never be silently reused. A crash
was the good outcome; silent version skew would have produced wrong numbers that looked fine.

## 5. We had access to order-book depth all along and were not collecting it

The literature agent corrected a standing assumption. cTrader exposes
`ProtoOASubscribeDepthQuotesReq` and `ProtoOADepthQuote` carrying **size per level**, which is
what book-imbalance research needs. Our 361k logged spot events contain prices only, which is
why we believed we had no book.

Depth capture is now implemented (`depth_quotes` table, storing each level change unaggregated
so arrival order survives) and running: **1,876 book events in the first 35 seconds** on four
crypto instruments.

## 6. What the literature says is worth our compute at one second

From 24 sources, the honest summary is that most published precursors live below our latency
floor. Two findings reframe the programme:

* **Kearns et al. (2010)**: an omniscient trader with perfect foresight over all US equities
  earns $21bn at a 10-second holding period, $760m at 1 second, $21m at 10 ms. Available money
  shrinks as the horizon shortens. Chasing speed moves toward the region where even perfect
  prediction earns almost nothing.
* **Byrd et al. (2020)**: for book-imbalance strategies, profit is allocated by latency
  **rank**, not absolute speed. We are last in that queue by orders of magnitude.

The one hypothesis with support at our horizon is cross-venue lead-lag: Albers et al. explain
10% to 37% of a lagging venue's 500 to 1000 ms forward return, with Binance consistently
leading. Full review: `docs/research/precursor-literature-2026-09-20.md`.

## Next experiments, in priority order

1. **H5, costs nothing, uses data we already hold:** no feature computable from top-of-book
   prices alone beats the cost floor at 1 to 60 seconds. If the null survives it goes in the
   lessons table and the council stops rediscovering top-of-book features.
2. **H1, needs collection started now:** Binance leads VALR at a horizon we can trade. Both
   feeds are free; the data only accumulates in real time.
3. **H4, one week of depth:** level-1 queue imbalance on the broker feed. Expected to fail,
   because a CFD book is an aggregation of liquidity-provider quotes rather than a real order
   book with queue priority, but it fails cheaply and closes the question.

## Data quarantine, from the audit

Not yet enforced in code, and it must be before the next zoo run. Full report:
`docs/results/data-quality-audit-2026-09-20.md`.

* **XRPUSD before November 2020 is a placeholder**: 228 consecutive byte-identical bars, 988
  bars with volume 1, prices at exactly 0.01.
* **Crypto weekend bars vanish 2018 to 2023**, so the meaning of a daily bar changes twice
  inside the sample.
* **Crypto D1 volume is synthetic** (exactly 1,434 for whole years).
* **Two as-of dates in one universe**: 21 symbols end on the 15 September session, 40 on the
  18th. "Trade on the last bar" is a three-day look-ahead for part of the universe.
* XPDUSD, XPTUSD and CHINA50 each miss over a year of consecutive weekdays.
* `data/cost_map.csv` was built from a 58-second recording. Nothing should read it.
