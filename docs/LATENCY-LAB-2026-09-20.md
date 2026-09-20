# Latency Laboratory: assessment before building

Written 2026-09-20, after inspecting the repository and the stored data. Deliverable 17 of the
owner's brief. Nothing in the engine was changed to produce it.

The brief's central question is "at what execution latency does an edge disappear?". This
document says what the engine can answer today, what it cannot, and the smallest honest first
experiment.

---

## 1. Current architecture

Eleven packages, 100 tests, one live broker.

| Layer | Where | State |
|---|---|---|
| Broker connection | `connection/client.py` | cTrader Open API over TCP, one session per account |
| Market data, bars | `market/bars.py` -> `data/market.db` | D1 and H1, 64 instruments, up to 12 years |
| Market data, ticks | `telemetry/logger.py` -> `data/telemetry.db` | 361,402 spot events, microsecond receive stamps |
| Long history | `T:\making-money\features\dukascopy` | 37 instruments, daily, 2003 onward |
| Features and models | `zoo/panel.py`, `zoo/models.py`, `strategy/` | 22 zoo candidates + 8 ladder strategies |
| Backtest | `backtest/harness.py`, `backtest/walkforward.py` | point in time, walk forward, deflated Sharpe |
| Costs | `backtest/run.measured_cost`, `zoo/portfolio.py`, `zoo/financing.py` | measured spread; broker swap split into fee and differential |
| Research loop | `research/experiment.py`, `council/`, `scout/` | LLMs propose, deterministic code decides |
| Memory | `data/research.db`: `trials` (295), `failures`, `lessons`, `episodes` (7), `sweep_results`, `zoo_results` | permanent |
| Risk | `risk/limits.py` | owner-signed numbers, deterministic, no AI path |
| Authority | `ops/authority.py` | HMAC grant required for live orders |
| Execution | `execution/sizing.py`, `scripts/live_trade.py`, `scripts/rehearsal.py`, `scripts/probe.py` | proven on demo and live |
| Ledger | `ledger/trade_log.py` -> `data/trade_log.db` | SARS-facing record of every real order |
| Publishing | `research/supabase_sink.py`, `scripts/push_live_state.py`, `dashboard/app.py` | Supabase + Render, hourly |
| Self-audit | `ops/audit.py` | 9 checks, UNKNOWN counts as FAIL |

## 2. Current trade lifecycle

```
bars (stored)  ->  strategy.generate_signals (shifted, no lookahead)
               ->  RiskOfficer.permit (LIVE_LIMITS)
               ->  size_position (broker margin, volatility stop)
               ->  ProtoOANewOrderReq with relative stop and target
               ->  ProtoOAExecutionEvent (ORDER_FILLED) or ProtoOAOrderErrorEvent
               ->  reconcile against the broker's own position record
               ->  ledger/trade_log + Supabase
```

Live-proven yesterday on ETHUSD. Two defects it exposed are fixed: relative stops are in the
API's fixed 1e-5 units, and a live trade must not inherit the rehearsal's log labels.

## 3. Timing and telemetry coverage TODAY

What exists:

* **Tick receive time**, `ticks.ts_utc`, microsecond resolution, 361k rows.
* **Application round trip**, `latency` table, 1,964 samples from `ProtoOAVersionReq`:
  **min 369 ms, mean 939 ms, max 4,941 ms**. This is the real machine-to-broker path from this
  house, and it is the single most important number in this document.
* **Order request time** in `scripts/probe.py` (`request_ts`) and an entry-to-fill delta.
* Bar timestamps, and `swaps.json` symbol specs.

## 4. Missing measurements

Of the brief's fifteen required timestamps, we currently capture three.

| Required | Status |
|---|---|
| Exchange/event timestamp | **MISSING, but available.** `ProtoOASpotEvent` carries `timestamp`; the logger discards it. Recording it gives true market-data latency |
| Market data reached machine | present (`ts_utc`) |
| Entered pipeline, feature start/end, inference start/end | **MISSING.** No live loop exists yet; research runs offline in batch |
| Decision, risk start/end, order created | **MISSING** |
| Order sent | partial (probe only) |
| Broker acknowledgement | **MISSING, available**: `ProtoOAOrder.utcLastUpdateTimestamp` |
| First fill / final fill | **MISSING, available**: `ProtoOADeal.createTimestamp` and `executionTimestamp` |
| Cancellation | not applicable yet |

Also missing: a per-event latency store, percentile reporting, attribution by
strategy/model/instrument/node/regime, and any replay that can inject delay.

## 5. Bottlenecks, measured not guessed

1. **The network to the broker dominates everything.** A 369 ms floor and a 939 ms mean means
   this engine is, structurally, a **one-second shop**. No code optimisation changes that.
   Any strategy whose edge dies inside one second is INFRASTRUCTURE_INFEASIBLE from this house,
   and no GPU fixes it.
2. **Tick data is thin and bursty.** 983 hours of wall time but only ~1.6 ticks/minute on the
   densest instrument, because the logger ran in sessions. One dense session exists:
   2026-09-16, 319,084 ticks in about 25 minutes across 24 instruments. Enough to prove
   machinery, far too short to measure an edge.
3. **Research compute is not a bottleneck.** The full 22-model zoo over 64 instruments and 23
   years runs in about 4 minutes on this machine, GPU included.
4. **No live loop exists.** Everything is batch. There is nothing to instrument end to end yet,
   which is why the first milestone must be a replay, not a live rig.

## 6. Where the Latency Laboratory integrates

A new `lab/` package, reusing what exists rather than duplicating it:

```
lab/clock.py      one monotonic + wall clock, span timers, writes to latency_events
lab/replay.py     delay injection: a signal formed at T executes at T + d, priced from the
                  finest data available at that moment (H1 bars now, ticks when dense)
lab/decay.py      runs the delay grid, builds the edge-decay curve, finds the survival
                  threshold, classifies the speed regime
lab/bench.py      machine benchmark: ingestion, serialisation, feature, inference, disk, net
```

It plugs into the existing evaluator, it does not replace it: `zoo/portfolio.py` keeps owning
position construction and costs, `backtest/walkforward.py` keeps owning honest splits, and
`research/episodes.py` keeps owning the durable record.

## 7. Minimum implementation for the FIRST experiment

Deliberately small, as instructed:

* `lab/replay.py` with a single function: given a signal series and a delay, return the
  positions actually achievable, priced at the delayed moment, with the measured spread paid.
* `lab/decay.py` to sweep the delay grid and compute the curve.
* `scripts/edge_decay.py --symbol EURUSD --strategy ewmac`.
* Two new tables. No live rig, no new threads, no async rewrite.

**Honest limit on the delay grid.** Daily and hourly bars cannot answer a 10 ms question, and
inventing that precision would be the exact dishonesty this project exists to avoid. So:

| Delay bucket | Data that can answer it | Status now |
|---|---|---|
| 0 to 1 second | tick stream, dense | only the 25-minute 2026-09-16 session |
| 1 to 60 seconds | tick stream, dense | same |
| 1 minute to 1 hour | ticks or M1 bars | not held; M1 is fetchable from the broker |
| 1 hour to 24 hours | **H1 bars, 6 years, 64 instruments** | **available now** |

The first experiment therefore runs in the band we can honestly measure: a daily signal
executed 0 to 24 hours late, at H1 resolution. It is also the band that matters for what we
actually hold: if a daily edge dies after 2 hours, our 0.9 second path is irrelevant and the
question is answered forever.

## 8. Experiment schema

```
experiments(
  experiment_id TEXT PRIMARY KEY,     -- ulid-style, sortable
  created_ts, hypothesis, question,
  kind,                                -- backtest | replay | paper | live
  strategy, strategy_version, model_version,
  instruments, period_start, period_end, data_hash, dataset_rows,
  cost_model, latency_model, config_json, seeds,
  code_commit, machine,
  status,                              -- running | complete | failed
  result_json, verdict, reason,
  capital_allocated_zar, capital_at_risk_zar, realised_pnl_zar,
  information_gained, next_experiment
)

latency_events(
  event_id, experiment_id, ts_utc, stage, strategy, model, instrument, exchange,
  node, mode, regime, value_ms, span_id, parent_span_id
)

edge_decay(
  experiment_id, strategy, instrument, delay_ms,
  gross_return, net_return, ev_per_trade, win_rate, profit_factor, sharpe, max_dd,
  spread_paid, fees, funding, slippage, fill_rate, missed_rate, adverse_selection,
  n_trades, n_obs
)
```

`trials` keeps counting every candidate for the multiple-testing bar; `episodes` keeps the
narrative. `experiments` is the reproducibility record the brief asks for, and it links to
both.

## 9. Storage changes

* `data/research.db`: add the three tables above. No existing table changes shape.
* `data/telemetry.db`: add `server_ts` and `recv_latency_ms` to `ticks` (nullable, so old rows
  stay valid), and record `ProtoOASpotEvent.timestamp` from now on.
* Large replay outputs go to `T:\making-money\sweeps\latency\`, not into git.
* Supabase gains nothing yet. The dashboard shows a latency summary only once the curve exists.

## 10. Implementation plan

**Stage A, today.** Tables, `lab/replay.py`, `lab/decay.py`, `scripts/edge_decay.py`. One
strategy, one instrument, H1 delay grid, curve, threshold, episode recorded. Prove the method.

**Stage B.** Record the broker's own timestamps: spot `timestamp`, order
`utcLastUpdateTimestamp`, deal `createTimestamp` and `executionTimestamp`. Then we can measure
true market-data latency and true time-to-fill rather than guessing.

**Stage C.** Run the decay sweep across every surviving candidate and classify each into a
speed regime from measured decay, flagging anything under one second as
INFRASTRUCTURE_INFEASIBLE from this location.

**Stage D.** Fetch M1 bars and run a continuous tick logger to open the 1 second to 1 hour
band, which is currently unmeasurable.

**Stage E.** Decompose net edge into prediction, spread, fees, slippage, funding and latency
cost, so the engine can say which half is broken.

**Stage F.** The R2,000 graduation ladder and the research-cost-per-validated-edge accounting.

**Stage G.** Only if a surviving edge needs it: the live instrumented loop, the machine
benchmark, and any hardware spend, each justified by a measured gain.

Stages A to C need no money and no live orders. Stage D needs the machine left running. Stage
F needs the owner's decision on the R2,000.
