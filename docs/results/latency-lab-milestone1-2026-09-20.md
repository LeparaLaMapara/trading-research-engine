# Latency lab, milestone 1: the first edge-decay curves

Protocol and architecture assessment: `docs/LATENCY-LAB-2026-09-20.md`.
Code: `lab/replay.py`, `lab/decay.py`, `lab/registry.py`, `scripts/edge_decay.py`,
`scripts/latency_report.py`. Every run is a row in `experiments`, every curve a set of rows in
`edge_decay`.

## The machine's measured latency, as distributions

`ProtoOAVersionReq` round trip, 1,967 samples, this house to the broker:

| min | median | p90 | p95 | p99 | max | jitter (IQR) |
|---|---|---|---|---|---|---|
| 369 ms | 949 ms | 1,109 ms | 1,639 ms | 3,543 ms | 4,941 ms | 403 ms |

Market data receive, first samples after the logger began recording the broker's own event
stamp: BTCUSD 216 ms, ETHUSD 285 ms, ADAUSD 4,197 ms.

Two facts worth stating plainly:

* **This is a one-second shop.** Any edge that dies inside about one second is
  INFRASTRUCTURE_INFEASIBLE from here, and no code change alters that.
* **The broker stamps only about 9% of spot events**, so market-data latency can be measured
  on a minority of ticks. A closed market also replays its last quote on subscribe, which
  looks like 36 hours of latency unless it is filtered as the stale snapshot it is.

## Edge decay, daily signals executed late (H1 pricing, 6 years)

`ma_trend` on EURUSD, the full curve:

| requested | effective | net return | Sharpe | EV/trade | win rate | profit factor | trades |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 0.073 | 0.16 | 18.6 bps | 35.9% | 1.26 | 39 |
| 1 h | 1 h | 0.073 | 0.17 | 18.7 bps | 35.9% | 1.26 | 39 |
| 2 h | 2 h | 0.075 | 0.17 | 19.1 bps | 35.9% | 1.26 | 39 |
| 4 h | 4 h | 0.062 | 0.14 | 15.8 bps | 35.9% | 1.22 | 39 |
| 8 h | 8 h | 0.067 | 0.15 | 17.1 bps | 30.8% | 1.25 | 39 |
| 12 h | 12 h | 0.062 | 0.14 | 15.9 bps | 30.8% | 1.21 | 39 |
| 24 h | 24 h | **-0.028** | -0.06 | -7.1 bps | 33.3% | 0.91 | 39 |
| 48 h | 48 h | -0.011 | -0.02 | -2.8 bps | 30.8% | 0.96 | 39 |

10 ms, 1 s, 60 s and 15 min were **SKIPPED, not estimated**: hourly bars cannot price them.

Survival threshold 12 hours, conservative operating target 3 hours, regime `multi_hour`,
feasible from this machine by a factor of about 11,000.

## The sweep

Four strategies on three instruments, same protocol:

| | EURUSD | XAUUSD | USDJPY |
|---|---|---|---|
| ma_trend | 12 h | at least 49 h | at least 48 h |
| vol_scaled | at least 48 h | at least 49 h | at least 48 h |
| mean_reversion | at least 48 h | **no edge at any delay** | **no edge at any delay** |
| multi_timeframe | at least 48 h | at least 49 h | at least 48 h |

"At least" means the curve never crossed zero inside the delays tested, so the number is the
edge of the ruler, not the edge of the strategy. The code flags this rather than printing a
threshold that looks measured.

## What this settles

1. **Speed is not our problem.** Every daily strategy tested tolerates hours of delay while
   our order path is about one second. Spending on faster hardware or hosting would buy
   nothing measurable, so it is not recommended.
2. **The interesting question moves.** If delay costs nothing, the losses are coming from
   costs and from the absence of an edge, which matches the 19 September finding.
3. **The sub-hour band is unmeasurable today**, and that is now a named data gap rather than
   an assumption: it needs M1 bars and a continuously running tick logger.
4. **These curves are decay curves of weak edges.** A Sharpe of 0.16 over 39 trades is not an
   edge, and the shape of its decay is correspondingly uncertain. The method is proven; the
   strategies still are not.
