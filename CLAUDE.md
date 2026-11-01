# CLAUDE.md

## What this project is

An **autonomous trading research engine** (owner: Thabang, GitHub `LeparaLaMapara`). A
research system that happens to trade — not a bot. It builds on the standalone
`ctrader-connect` project for the cTrader/IC Markets Open API connection. Live account,
~$10 balance.

## Rule zero: autonomy, and the single exception

On 2026-09-16 the owner granted this project **full autonomy**, in his own words: build the
capability yourself without pausing, change permissions or whatever process needs to happen,
prompt yourself, test yourself, spawn agents and agent teams, without him being involved.

**The only exception is moving real money in the live account.** That is the one pause, and
his involvement resumes when the system says it is ready to trade.

So, concretely:

| Proceed without asking | Stop and ask |
|---|---|
| Writing, refactoring, deleting code; installing deps | Sending an order on the LIVE account |
| Changing config, permissions, CI, schedules | Anything that can change a live balance |
| Reading the broker: bars, specs, balance, margin, reconcile | Raising the authorised capital ceiling |
| Demo orders, rehearsals, probes on demo | |
| Spawning agents, running loops, self-testing | |

**Reading the broker is not trading.** Bars, symbol specs, balances and margin quotes move
no money and need no approval.

That boundary is enforced in code, not trust: `ops/authority.py` requires an owner-signed
HMAC grant whose secret (`LIVE_AUTHORITY_SECRET`) is set only in the live environment and has
never been present in a development session. An agent here can write the grant file, edit the
module, and grant itself every permission in this repo, and still cannot forge the signature.
`risk/limits.py` denies independently while `LIVE_LIMITS` is unconfigured. `ops/audit.py`
check `live_money_stays_gated` fails loudly if either lock is open.

This is a control, not a proof: an agent with filesystem access could delete the call site.
What the design buys is that doing so is a visible change to a named module rather than a
silent drift. No accident gets through; a deliberate bypass leaves evidence.

### Update 2026-09-23: standing live authority

The owner removed the one exception, in his words: "I don't want it to ask me anymore ... the
objective is to get better, learn as much as you can and start beating the market", accepting
losses. So the engine now trades the live account on its own:

- `scripts/engine_loop.py` runs always, kept alive by `scripts/engine_supervisor.py` (restarts
  it a minute after any exit), which starts at logon from
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TradingEngine.vbs`. Task
  Scheduler would also cover reboots without a logon but needs admin rights this session lacks.
  Logs and heartbeat: `T:\making-money\engine\`. Hourly: record E03 data, publish live state,
  run `scripts/trader_step.py` (E05 Ethereum 20-day trend, one decision per UTC day, only
  touches positions labelled `engine-E05`).
- The secret lives outside the repo in `~/.trading-research-engine/live_secret`;
  `ops.authority.ensure_standing` renews the 30-day grant (ceiling R2,000 since the owner's R1,000 deposit on 2026-09-23;
  it was R600).
- Still binding: the signed LIVE_LIMITS (6% risk/trade, 2 positions, 40% drawdown, $20 floor);
  the trader latches `halted` in `data/engine_state.json` on the floor or the drawdown and never
  trades again until the owner removes it. The audit fails if limits or ceiling drift.
- To stop everything: delete the Startup launcher, end the pythonw/python engine processes,
  delete the secret file, and run
  `python -m ops.authority --revoke`.
- Research continues: any later strategy experiment that passes and that the account can afford
  replaces E05 as the live rule.
- Dashboard (Render free tier): a Supabase pg_cron job `keep-trading-dashboard-awake` pings
  `/healthz` every 10 min, 04:00 to 19:59 UTC only (~500 of the 750 free hours a month; nights
  sleep on purpose). Do NOT use GitHub Actions for pings: the repo is private and 2,000 free
  minutes a month would run out. The family section reads `deposited_usd`, `peak_equity` and
  `halted` from making_money.trading_account (published by scripts/push_live_state.py).

### Update 2026-10-31: the goal is profit

The owner reset the goal: be the best on cTrader and **make profits, accurately, with the
capital the account has now**. The honesty gates below stay, because they are what keeps a
loss from looking like an edge; they are the means, not the goal. Plan (owner said "Yes"):
1. intraday holds (no overnight financing, and a 0.01 lot FX stop then fits the 6% limit),
   the economic calendar and entry guards; 2. the FX fix pattern and the FOMC-day dollar,
   with meta-labelling; 3. an RD-Agent-style idea loop feeding the gate; 4. demo forward test,
   then live. Step 1 is built: `news/calendar.py` (weekly Forex Factory feed, merged into
   `data/calendar.json`; the Hugging Face 2007-2025 history is mistimed and NOT used),
   `execution/guards.py` (rollover 17:00 New York -30/+60 min, high-impact news +-30 min,
   live spread > 2x measured median; all fail closed; exits never blocked), checked in
   `scripts/trader_step.py` before opening and in `scripts/live_trade.py` on the real quote,
   and `CostModel.financing_annual` in `backtest/harness.py` (charged per rollover held).

### Update 2026-11-01: the discovery machine and the forward gate

Owner approved: search wide on 2014-2022 (every rule counted), test a short list ONCE on the
sealed 2023-2026-09 vault (`research/vault.py`, log `docs/results/vault-log.jsonl`, a second
opening per experiment is refused), then paper-trade survivors on live quotes. A rule goes live
when the forward mSPRT says edge > 0 at 5% (Holm over the forward candidates) and its paper
result net of live spread is positive: programme rule 4 in `docs/programme/README.md`.
Plan: `docs/plans/discovery-machine-2026-11.md`. First search E13 (hourly windows): FAIL.

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

## How research is done (since 2026-09-22)

A budget of **10 pre-registered experiments**, not a daily search. Rules in
`docs/programme/README.md`, register in `docs/programme/register.json`, status via
`python -m research.programme`. In short:

- Pre-register, commit and push BEFORE running. `ops/audit.py` checks the git order.
- The daily CI run refreshes data and runs the audit. It does not test strategies: repeats
  only raised the deflated-Sharpe bar for real ideas.
- Ideas come from resolvable papers and the engine's own cost measurements. The council no
  longer picks strategies (46% right about its own proposals).
- Stop rule: 10 spent with no pass means this account at this broker has no edge worth
  trading; the project continues as a measurement lab. The audit fails when that happens.
- A pass means demo paper trading, never a live order by itself.
- **Reading room (from 2026-09-29):** a weekly workflow (`reading.yml`, `scout/reading_room.py`)
  reads across finance, economics, statistics, maths, physics and CS, grounds and red-teams
  idea cards, and ranks `docs/research/queue.json`. It never tests or trades. Keep
  `docs/research/engine-facts.md` true: every paper is read against it.

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
- Runs on **live** (`CTRADER_ENV=live`, the live account, id in .env) to measure the real broker.
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
