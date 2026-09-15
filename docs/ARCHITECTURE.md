# Architecture and long-term direction

Status of this document: **direction, not a work order.** Nothing in the LONG-TERM sections
below is scheduled, approved for implementation, or permitted to destabilise the working
system. It exists so that architectural decisions taken now do not accidentally weld the
research intelligence permanently to one broker.

The near-term build plan is `PLAN-2026-09-15.md`. The project charter and hard rules are
`../CLAUDE.md`. This document sits above both and changes more slowly than either.

Written 2026-09-15. Every CURRENT statement was read out of the repository rather than
recalled, and the verification notes say how.

---

## 1. The one-line framing

**The cTrader integration is Venue Adapter #1, not the boundary of the system.**

The system being built is a *Global Autonomous Quantitative Research and Market Engine*: a
locally controlled, extensible system that researches quantitative hypotheses, tests them
scientifically, tries to falsify its own discoveries, allocates capital under deterministic
constraints, executes through one or more venues, measures what happened, learns from it, and
repeats.

It is a **research system first and a trading system second**. That ordering is not modesty.
It decides what gets built, what gets measured, and what counts as success.

### The central research question

> **Can an autonomous scientific system continuously discover, falsify, validate, deploy,
> monitor, and retire quantitative market edges faster than those edges decay?**

Everything else in this document is in service of being able to answer that honestly.

---

## 2. CURRENT: what the repository actually implements

Read from the repo on 2026-09-15. Roughly 6,800 lines of Python across 16 packages, 108
passing tests.

### 2.1 Venue connection (cTrader only)

| Component | File | What it does |
|---|---|---|
| OAuth service | `../ctrader-connect/app/oauth_server.py` | Hosted grant flow, password gated, deployed |
| Token lifecycle | `../ctrader-connect/app/tokens.py`, `connection/tokens.py` | Exchange, refresh, shared store |
| Connection | `connection/client.py` | App auth, account auth, symbol list, spot subscribe |
| Account state | `market/account.py` | Balance and `leverageInCents` from the broker |
| History | `market/bars.py` | cTrader trendbars to OHLC |
| Operator tools | `scripts/accounts.py`, `reconcile.py`, `probe.py`, `preflight.py` | List, reconcile, probe, prove |
| One-shot order | `../ctrader-connect/connector/trade.py` | Dry run by default, sends only on `--confirm` |

Tokens persist in Supabase (`making_money.ctrader_tokens`) rather than a file, so the hosted
service, the scheduled run and local tools share one live credential.

### 2.2 Research pipeline

```
Scout (arXiv) ─┐
               ├─> Council proposes ─> validator ─> failure registry ─> assumption tests
Council ───────┘                                                              │
                                                                              v
   lessons + calibration <── deflated Sharpe <── walk-forward backtest <── session filter
```

* `scout/` fetches real arXiv papers, stores a Transfer Card per paper with a resolvable
  identifier, and maps a method to an implementable strategy kind or to nothing.
* `council/` runs a cross-model council: one model proposes, another red-teams.
  `council/budget.py` refuses a call **before** it is made if it would exceed the run's cap.
* `strategy/` holds a six-rung ladder (`buy_hold`, `random`, `ma_trend`, `vol_scaled`,
  `multi_timeframe`, `mean_reversion`), a registry and a validator that rejects prohibited
  patterns such as martingale.
* `analysis/` provides stationarity and Hurst tests, a session filter derived from measured
  spreads, regime and pairs utilities.
* `backtest/` runs a point-in-time walk-forward with measured costs and computes a deflated
  Sharpe against the honest trial count.
* `research/experiment.py` is the end-to-end loop.

### 2.3 Memory and learning

* `research/registry.py` records every failure and, separately, **every candidate ever
  scored**. Hard tabu applies only to an exact re-run of the same variant, expires by tenure,
  and is overridden by aspiration. The trial count is the `N` used to deflate Sharpe.
* `research/calibration.py` scores the falsifiable prediction each proposal commits to
  before its backtest runs.
* `research/lessons.py` distils each cycle deterministically into lessons that carry a win
  rate, are injected into the next cycle's prompt, and are **retired when they never help**.

### 2.4 Risk, ledger, reporting, operations

* `risk/limits.py` is a **fail-closed stub that denies every order**. The section 1 limits are
  not configured, so nothing can trade. This is the intended state, not an oversight.
* `ledger/` holds the SARS trade log and the sweep ledger.
* `dashboard/app.py` is a family-facing FastAPI page: four rand-denominated numbers, four
  charts, and a goal channel where a person states an objective in their own words and
  deterministic code in `research/goals.py` judges feasibility and may refuse.
* `ops/audit.py` runs eight deterministic self-checks with no model in the path, where a
  check that cannot run counts as failure rather than success.

### 2.5 Runtime, scheduling and storage

* **Scheduling is GitHub Actions**, `.github/workflows/research.yml`, daily at 05:00 UTC.
  `scripts/scheduler.py` exists as a Render worker entrypoint but is not the deployed path.
* **There is no Supervisor, no systemd unit, no Docker, and no container orchestration
  anywhere in either repository.** Verified by search. Process management today is the CI
  runner plus two Render web services.
* Local state: four SQLite databases (`market`, `research`, `telemetry`, `trade_log`) plus
  content-hashed Parquet snapshots. Large artifacts are configured to `T:\making-money`.
* Shared state: Supabase, schema `making_money`, reached through PostgREST profile headers.

### 2.6 What the system has actually achieved

Stated plainly, because an architecture document that overstates its base is useless:

* **Strategies that have passed the gate: zero.** Every candidate tested has failed the
  deflated Sharpe bar once real costs were counted.
* **Orders ever transmitted: one.** It was rejected for insufficient margin.
* **The risk layer has never permitted anything**, by design.
* Account: one funded live account, $30, 1:50 leverage. No demo account exists.

---

## 3. IN DEVELOPMENT

Work that is started and partially landed.

* **Preflight capability proof** (`scripts/preflight.py`): exercises connect, authenticate,
  read symbols, read balance and leverage, read history, list positions, build a valid order
  and stop before sending, and confirm the risk layer refuses. Currently reports one failure:
  no demo account exists, so order-path code has nowhere safe to be proven.
* **Learning loop hardening**: lesson attribution is deliberately crude (lessons on screen
  during an improving cycle are credited). Whether that attribution carries signal is an open
  measurement, not a settled result.
* **Execution telemetry** beyond a single rejected order. The live account's only unique
  value is measuring real fills, and it has not yet measured one.

---

## 4. PLANNED

Agreed direction with a written plan, per `PLAN-2026-09-15.md`. Not yet built.

* Deep history from tick archives, replacing the current shallow bar sample.
* Point-in-time macro features using vintage-aware sources, so a backtest cannot see revised
  figures that were not knowable at the time.
* Validation hardening: purge and embargo, combinatorial cross-validation, probability of
  backtest overfitting alongside deflated Sharpe, and a genuinely untouched holdout.
* Mechanism-before-search: a candidate states who is on the other side of the trade and why
  they accept the loss, before it is allowed to consume trials.
* The section 1 risk numbers, which unblock the risk layer.
* A model-agnostic gateway so the reasoning model is a configuration value rather than a
  dependency.

---

## 5. LONG-TERM RESEARCH DIRECTION

**Not scheduled. Not approved for implementation. Documented so the current design does not
foreclose it.**

### 5.1 The shape

Today:

```
Local Quant System  ->  cTrader  ->  Broker  ->  Markets
```

Intended direction:

```
                Global Quant Engine
                       |
      +----------------+----------------+
      |                |                |
   Research          Risk           Portfolio
      |                |                |
      +----------------+----------------+
                       |
                Venue Abstraction
                       |
   +-----------+-------+-------+-----------+
   |           |               |           |
cTrader     Brokers        Exchanges    On-chain
   |           |               |           |
  FX/...   Global Assets      Crypto      DEX/DeFi
```

The diagram communicates intent, not a required implementation design.

The governing principle: **the intelligence stays independent of any individual venue.**

```
Local Quantitative Intelligence
  -> Market/Venue Abstraction Layer
    -> Execution Adapters
      -> External Markets
```

### 5.2 Conceptual component map

```
Global Quant Engine
├── Research System
├── Hypothesis Generation
├── Literature/Paper Research
├── Mathematical Modelling
├── Data Engineering
├── Feature Discovery
├── Statistical Learning
├── Machine Learning
├── Strategy Generation
├── Backtesting
├── Simulation
├── Walk-Forward Validation
├── Adversarial/Falsification Testing
├── Paper Trading
├── Portfolio Construction
├── Capital Allocation
├── Deterministic Risk Engine
├── Execution Optimisation
├── Monitoring
├── Experiment Memory
└── Venue Adapters
    ├── cTrader
    ├── Global Broker(s)
    ├── Centralized Exchanges
    ├── Blockchain/DEX
    └── Future Venues
```

Venue classes that could eventually have adapters, **directionally and not as an instruction
to implement**: FX, CFDs, equities, ETFs, futures, options, commodities, bonds and fixed
income, crypto spot, crypto futures and perpetuals, centralised exchanges, decentralised
exchanges, DeFi protocols, prediction markets where legally permitted, and other
machine-accessible financial markets.

### 5.3 Autonomous research cycle

The research layer should eventually do more than execute human-written strategies:

```
discover -> hypothesize -> research -> implement experiment -> backtest
  -> attempt to falsify -> stress test -> compare -> reject/accept
  -> paper trade -> tiny live experiment -> evaluate -> learn -> repeat
```

Specialist functions could include a quantitative researcher, statistician, mathematician,
econometrician, market-microstructure specialist, ML researcher, execution researcher,
portfolio researcher, risk researcher, adversarial reviewer, replication researcher and
literature researcher.

**The number of agents is not the point.** The point is that research is *parallelizable and
adversarial*. A hypothesis is never accepted because one agent found impressive historical
performance. Other processes actively try to destroy it by testing for:

overfitting, look-ahead bias, survivorship bias, leakage, multiple-hypothesis effects,
unrealistic fills, transaction costs, spread, slippage, latency, liquidity constraints,
capacity constraints, regime dependence, model instability, data-quality problems, and
accidental correlations.

**The system should become progressively harder to convince that an apparent edge is real.**

### 5.4 Opportunity classes

Research directions, not claims of profitability. Every proposed edge must survive empirical
testing:

statistical arbitrage, relative value, factor strategies, volatility strategies, cross-market
relationships, market microstructure, execution effects, basis and funding relationships,
cross-venue discrepancies, regime-dependent strategies, portfolio effects, and other
quantitatively testable hypotheses.

The engine should not remain tied to single-instrument directional trading.

### 5.5 Market abstraction

There is no single universal "global market". OTC markets, exchanges, brokers, ECNs, order
books, liquidity providers, centralised crypto exchanges, blockchain liquidity pools and
decentralised protocols have genuinely different structures.

The goal is **not** to force every market into an identical representation. It is an
extensible abstraction that normalises enough for cross-market reasoning while preserving
venue-specific characteristics where they matter.

### 5.6 Capital philosophy

The objective is **not** "make as much money as possible". That objective rewards
catastrophic risk taking, and on a small account it does so quickly.

The objective is to discover **reproducible positive expected value** and to maximise
long-run risk-adjusted and geometric capital growth **subject to hard constraints**.

Capital is earned through evidence:

```
simulation -> out-of-sample validation -> paper trading -> tiny live allocation
  -> evidence -> larger allocation
```

And withdrawn the same way:

```
live evidence -> deterioration detected -> allocation reduced or removed -> research resumed
```

**The system must always be allowed to conclude NO TRADE. Doing nothing is a valid decision,
and frequently the correct one.**

### 5.7 Risk boundary: research autonomy is not financial authority

These are separate powers and should never be merged.

Research autonomy may eventually be substantial. Execution stays behind deterministic controls
including maximum position sizes, maximum exposure, maximum strategy allocation, maximum
portfolio allocation, drawdown limits, daily and weekly loss limits, leverage limits, venue
limits, kill switches, credential isolation and withdrawal restrictions.

**The reasoning or research agent must not hold credentials capable of moving or withdrawing
arbitrary funds.** The current `risk/limits.py` already embodies the weaker form of this rule:
plain code, no prompt, no override path, fail-closed.

### 5.8 Scientific provenance

This is a Git-based project, and reproducibility is a first-class requirement rather than a
nicety. Every important experiment, and eventually every deployed strategy, should be
reproducible, with live decisions associable to:

strategy ID, Git commit SHA, model version, dataset or data snapshot, experiment ID,
hypothesis ID, configuration, risk-policy version, execution adapter, timestamp, and the
research evidence supporting deployment.

### 5.9 Local-first, portable

The intelligence should remain capable of running locally: agents, models, research,
backtesting, databases, experiment tracking, orchestration, risk logic, portfolio logic and
monitoring.

External connectivity should be needed only for things that inherently live outside: live
market data, broker and exchange connectivity, blockchain networks, execution and settlement.

The architecture should stay portable enough that workloads can move from local machine, to
Docker, to a dedicated machine or home server, to a VPS, to distributed infrastructure,
**without redesigning the research system**.

---

## 6. Architectural couplings that would make multi-venue expansion harder

**Identified, not scheduled for repair.** Recorded so the cost is known when the question
arises. None of these is a defect in the current system, which was correctly built for one
venue.

1. **Venue semantics live inside the research layer.** `research/goals.py` hardcodes
   `MIN_LOT_NOTIONAL_USD`, `ACCOUNT_LEVERAGE`, `PIP_VALUE_MIN_LOT_USD`, `TYPICAL_STOP_PIPS`
   and a lot-size floor. These are cTrader and FX concepts sitting in the layer that is
   supposed to be venue-independent. Any second venue with different contract sizes,
   settlement or margin rules meets this first.

2. **There is no venue field anywhere in the data model.** `trials`, `failures`, `lessons`,
   `bars`, `symbol_spec` and `trade_log` all key on `symbol` alone. Two venues quoting the
   same symbol would silently collide, and no past result could be attributed to where it was
   measured.

3. **`connection/client.py` is the connection interface *and* the cTrader implementation.**
   There is no port or adapter boundary, so a second venue has nothing to implement against.

4. **The strategy contract is single-instrument, directional and bar-based.**
   `Strategy.generate_signals(bars) -> {-1, 0, +1}` cannot express a spread, a multi-leg
   trade, a relative-value position, a basis trade or anything order-book driven. Most of the
   opportunity classes in section 5.4 do not fit this signature.

5. **The cost model is FX-shaped.** `backtest/run.py::measured_cost` is built on pips and
   `pip_position`. Equities commissions, futures ticks, crypto maker/taker fees, funding
   rates and on-chain gas have no representation.

6. **Money is a bare float in USD.** There is no currency or asset-class type, no settlement
   currency and no conversion boundary. Multi-currency and multi-asset accounting has nowhere
   to live.

7. **No experiment or trade records a code version.** Content hashing exists for datasets
   (`telemetry/store.py`) which is real partial provenance, but no Git SHA, model version or
   config version is attached to any trial, prediction or trade. Section 5.8 is currently
   unreachable for that reason, and the gap widens with every result recorded.

8. **`symbol_spec` mirrors the cTrader symbol message.** It is the de facto instrument model,
   so instrument metadata is already venue-shaped.

9. **Scheduling is tied to one CI provider.** The daily cycle is a GitHub Actions workflow
   with cache-based state persistence. There is no Supervisor, systemd unit or container, so
   the portability ladder in section 5.9 starts from nothing rather than from a process
   definition.

10. **Time and calendar assumptions are FX-shaped.** Session filters and bars-per-year
    constants assume a continuous weekday market. Exchange hours, auctions, holidays and
    24/7 crypto are not represented.

---

## 7. Relationship to the current cTrader work

The cTrader implementation is **the first real experimental environment**, and it continues
according to its existing design. It is where execution reality gets measured, and no
simulation substitutes for that.

Nothing in section 5 modifies the current roadmap, and none of it justifies destabilising a
system that is under active development. The purpose of this document is narrower and simply
stated:

**Do not let cTrader become the conceptual boundary of the architecture.**
