# CLAUDE.md

## What this project is

An **autonomous trading research engine** (owner: Thabang, GitHub `LeparaLaMapara`). A
research system that happens to trade — not a bot. It builds on the standalone
`ctrader-connect` project for the cTrader/IC Markets Open API connection. Live account,
~$10 balance.

## The one constraint everything flows from

The owner has stated he cannot verify strategy mathematics by inspection. So the system is
designed to be **verifiable by a non-expert**. Three rules override everything:

1. **LLMs never decide.** They propose. Deterministic code decides.
2. **The risk layer is plain code with hard limits — no prompt, no argument, no override,
   no AI path.** (`risk/limits.py`, fail-closed until Phase 1d.)
3. **No meaningful capital goes live** until the §7 graduation criteria are met in full and
   signed off.

## The $10 account

A **measurement instrument**, not a validation environment. Use it to measure real
execution (spread/slippage/rejection/swap/latency) that demo fakes. Strategy validation is
demo + backtest. The account is *funded* to viability (~$200+ from the risk table), never
*grown* to it. It is live → trades are taxable events → the trade log starts at trade one.

## Hard rules

- **Secrets never enter this repo.** Reuses `ctrader-connect` creds via `.env` (gitignored)
  and its `tokens.json` (via `TOKEN_STORE`). No client secret, no tokens, ever committed.
- **Demo/telemetry before live strategy.** Phase 1a is passive (no orders). Live probe
  trades (1a-active) are tiny, gated, and only to buy execution data.
- **Simplest-first (complexity ladder §9).** Nothing past the backtest harness is built
  until the harness is trusted. A more complex model replaces a simpler one only if it wins
  out-of-sample after costs, past multiple-testing correction.
- **Anti-hallucination:** no paper without a fetched resolvable identifier + stored text; no
  number not produced by re-runnable code; every dataset seeded, versioned, hash-recorded.
- Stays a separate repo from `ctrader-connect` (that project's charter forbids merging).

## Layout

```
config/       instruments basket, session seeds (real filter derived in 1b), settings
connection/   reusable cTrader auth bootstrap + token access (reuses ctrader-connect creds)
telemetry/    PHASE 1a: logger, store (SQLite + hashed Parquet), costmap, units
ledger/       SARS trade log + 20/80 sweep ledger (schemas now, rows later)
risk/         PHASE 1d Risk Officer — fail-closed stub until §1 numbers are locked
backtest/     PHASE 1c — empty until 1a cost map exists
tests/        pip math, tz, hash determinism, cost-map, sweep, fail-closed risk
```

## Current state (2026-08-06)

- **Phase 1a built.** Passive telemetry logger + store + cost map + ledger/risk scaffolds +
  unit tests. Reuses the proven `ctrader-connect` auth sequence.
- Runs on **live** (`CTRADER_ENV=live`, account 46748922) to measure the real broker.
- **Deferred, owner sign-off before the relevant phase:** §1 hard-limit numbers and §7
  graduation numbers (lock before 1d); tax practitioner; IC Markets FSCA/ODP status;
  minimum viable live funding.

## Running it

```bash
pip install -e ".[dev]"
pytest
python -m telemetry.logger --duration 120   # passive; snapshots on stop
python -m telemetry.costmap                  # spread-by-hour cost map
```
