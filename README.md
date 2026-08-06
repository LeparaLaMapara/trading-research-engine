# trading-research-engine

A **research system that happens to trade**, not a trading bot. It exists to find and
verify statistical edges the owner cannot check by inspection — so its prime directive is
*verifiability by a non-expert*: **LLMs propose, deterministic code decides, and the risk
layer has no AI path to it.**

Built on top of the standalone [`ctrader-connect`](../ctrader-connect) connection (OAuth +
Open API). This repo is the research system; the connector stays lean and separate.

## The $10 live account is a measurement instrument, not a strategy validator

At the minimum tradeable size (~$1,000 exposure vs ~$10 equity) the risk rules are
physically unachievable and results are statistically meaningless. Its unique, genuine
value is measuring **real execution** — spread, slippage, rejections, swap, latency — that
demo servers fake. Strategy validation happens on demo + backtest, using costs measured
here.

## Phase 1a — Execution Telemetry (what's built)

Passive only. No orders, no strategy, no risk decisions, no AI.

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -e ".[dev]"
cp .env.example .env        # reuses ctrader-connect creds; TOKEN_STORE -> its tokens.json

pytest                                    # unit suite
python -m telemetry.logger --duration 120 # log live for 2 min, then snapshot
python -m telemetry.costmap               # build the spread-by-hour cost map
```

- `telemetry/logger.py` — subscribes to the basket (`config/instruments.py`), records every
  tick (spread in price and pips), probes API latency, snapshots to hash-stamped Parquet.
- `telemetry/store.py` — SQLite + reproducible Parquet snapshots (content-hashed, §5).
- `telemetry/costmap.py` — median spread + tick volume by (pair × hour-of-week SAST).
- `ledger/` — SARS trade log + the 20/80 sweep ledger (schemas now, rows when trading starts).
- `risk/` — the Risk Officer, **fail-closed** until Phase 1d locks the §1 limits.

## Roadmap

1a Telemetry ✅ → 1a-active (gated probe trades) → 1b session filter (derived from data) →
1c backtest harness → 1d risk layer (needs owner's §1 numbers) → 1e first simple strategy →
1f explainer/weekly report → then Scout / Council / calibration / failure registry.

See `CLAUDE.md` for the charter and hard rules, and
`../.claude/plans/glistening-crunching-forest.md` for the full Phase 1 plan.
