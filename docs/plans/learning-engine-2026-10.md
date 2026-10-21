# Learning engine: gap analysis and build order (October 2026)

Owner's design, approved 2026-10-21: **the objective is to learn, not earn.** Maximise decisive
verdicts per week (ideas clearly ruled in or out), with an honest N, deflated Sharpe, PBO
(Bailey, Borwein, Lopez de Prado and Zhu 2014, CSCV) and a Harvey-Liu-Zhu t > 3 bar for new
families. Never fool ourselves; never risk ruin.

Fixed boundaries for this build: the signed limits (6% risk a trade, 2 positions, 40% drawdown,
$20 floor) and the capital ceiling do not change; no live order is sent outside what the
engine's existing rules allow (today none: E07 and E08 are paused by A01). The repo is public:
no secrets, account numbers or tokens in commits.

## What exists, what is missing

| # | Component | Exists | Missing |
|---|---|---|---|
| 1 | Health check | `ops/audit.py` (8 checks, daily in CI, rows in `ops_checks`, dashboard lights); GitHub emails failed scheduled runs to whoever last edited the cron | Nothing tells the owner the same day in a place he looks. CI failed 18 to 20 Oct for three days unseen; the weekly Databricks job failed on 19 Oct unseen; the PC's Databricks upload fails silently into a log file. No email: `SMTP_PASS` is empty. |
| 2 | Demo fleet | `risk/limits.py` has `DEMO_REHEARSAL_LIMITS`; `scripts/rehearsal.py` demo order path; connection picks host from `CTRADER_ENV` | **No demo account.** The token grants one account, live. The Open API has no message that creates an account (its 40 requests include only AccountAuth, AccountLogout, GetAccountListByAccessToken). No forward-test runner, no fill log for forward tests, no candidate list. |
| 3 | Live account as cost meter | `research/live_check.py` (assumed vs measured spread for live rules), `trade_log.db` (57 rows, requested vs filled price), telemetry spreads, `backtest/run.py::measured_cost` | No per-fill comparison of live vs demo vs backtest assumption; the backtester's cost model is never calibrated from fills (slippage and swap are not fed back); no rule that picks "the single best forward candidate". |
| 4 | Sequential stopping + bandit | none | Always-valid p-values / SPRT on forward results; Thompson sampling of demo slots. |
| 5 | Breadth | `market.db` D1 bars for 64 symbols since 2014, H1 for 24 since 2020; `scripts/sweep_universe.py` (H1, 4 models) | A screen that runs each evidence family across the 40 to 60 instruments with one honest method. |
| 6 | Instrument choice | `scripts/universe.py` -> `docs/results/universe.json`: min lot, 2-ATR stop loss in USD, fits 6%? | Risk as % of equity at min lot, the 1 to 2% preference, a ranking the fleet and cost meter use. |
| 7 | Horizon and latency | `scripts/latency_report.py` (reads past probes), telemetry server timestamps, hourly engine loop | A standing round-trip latency measurement from this PC each hour; ticks recorded around forward fills; hourly decision bars for the fleet. |
| 8 | Families with evidence | Pre-programme zoo: `tsmom_12m`, `xs_momentum`, `short_reversal` (pooled, "trend fails on this set", "ML faint"); carry tested 2026-09-19 (falsified, `scripts/carry.py`, point-in-time OECD rates); E09 crypto carry FAIL | Calendar effects (turn of month, time of day) never tested. No per-instrument verdicts, no PBO on any family. Currency **value** needs PPP or real exchange rate data the engine does not hold: declared not tested, not faked. |
| 9 | Dashboard metrics | Story dashboard: money, tests, lessons, affordability, health lights | Verdicts per week, forward-test hours, backtest-vs-live cost gap, probability of ruin; a banner when a job failed. |

Also found while checking: PC and CI share one cTrader token lineage. The PC reads its own
`tokens.json` before the shared Supabase store, so when the access token expires (about
2026-11-15) whichever side refreshes first leaves the other with a dead token. Fixed in step 1
by making `tokens.load()` take the newest of file and shared store.

## Build order (branch `feat/learning-engine`, tests for each part)

1. **Health** (`ops/job_health.py`). Every scheduled workflow ends with a step that records
   `job:<name>` OK or FAIL in `ops_checks` and, on failure, opens (or comments on) one GitHub
   issue per job, labelled `job-failure`, so GitHub emails the owner the same day; success
   closes it. The PC's daily Databricks upload records `job:pc-dbx-upload` the same way. The
   dashboard shows a red banner at the top while any job's latest record is FAIL or overdue
   (daily > 26 h, weekly > 8 days). Token load picks the newest copy.
2. **Statistics** (`learning/stats.py`). PBO by CSCV; Harvey-Liu-Zhu t bar (3.0 new family,
   2.0 replication of a published family); always-valid p-values from a normal-mixture
   sequential probability ratio test (mSPRT, Johari, Pekelis and Walsh 2017) for both "edge >
   0" and "edge < worthwhile"; Thompson sampling; probability of ruin by simulation at the
   signed limits.
3. **Instrument choice** (`learning/instruments.py`). From live symbol specs + D1 ATR: risk %
   of equity at min lot with a 2-ATR stop, band 1-2% preferred, <= 6% allowed; writes into
   `universe.json`.
4. **Families + breadth screen** (`learning/families.py`, `learning/screen.py`). Pre-registered
   as **E10** (the last P1 slot), committed and pushed before it runs. Families: time-series
   momentum (1, 3, 12 months), FX carry (point-in-time rate differential), currency
   cross-sectional momentum (1 and 3 months, long top 3 / short bottom 3), short-term reversal
   (5 and 21 days), turn of month, time of day (USD intraday seasonality on H1). Every
   instrument with enough D1 history (cap 60). Net of measured spread, commission and the
   broker's financing fee; FX differential point-in-time. Every variant x instrument is a trial
   in N. Verdict per candidate: IN-SCREEN (t >= bar, family PBO < 0.5, deflated Sharpe at N >=
   0.5), OUT (upper 95% bound of net Sharpe below 0.3, the smallest Sharpe that serves the
   family goal), else UNDECIDED. Screen passers become forward candidates; the screen is never
   a live licence.
5. **Forward fleet** (`learning/fleet.py`). Hourly decision bars inside the engine loop's turn.
   Thompson sampling picks which candidates hold the demo slots. Mode `demo` (real orders on a
   cTrader demo account, real fills) when `DEMO_ACCOUNT_ID` is set; until then mode `paper`:
   fills simulated at the live bid/ask read from the live account (read-only), so forward
   results still pay the real spread. Every fill logged with quote, fill, latency and the ticks
   around it. mSPRT decides IN / OUT per candidate; the decision is final and counts as a
   verdict.
6. **Cost meter** (`learning/cost_meter.py`). Compares every live fill (trade_log) with the
   paper/demo fill and the backtest assumption (spread, slippage, swap, latency), writes the
   gap, and writes `data/cost_calibration.json`, which `measured_cost()` adds to the backtester's
   spread. Selects the single best forward candidate that has a forward IN verdict and fits the
   signed limits; in this build it only reports what it would do (dry run). A live rule still
   needs rule 4 of the programme (deflated Sharpe 0.95 at N) and the existing trader path.
7. **Latency** (`learning/latency.py`). Hourly, five request round trips to the broker from
   this PC, stored with the forward fills; send-to-fill latency on every demo fill.
8. **Dashboard** (`learning/metrics.py` -> Supabase `learning_metrics`; `dashboard/story.py`):
   verdicts per week, forward-test hours (demo and paper), cost gap, probability of ruin,
   health banner.

## How it is checked

`pytest` for every part; then a real end-to-end run on this PC: screen -> fleet step (paper)
-> cost meter dry run -> metrics published -> dashboard renders the new section. Merge by PR
the way the repo does (squash), except the E10 pre-registration, which goes to main on its own
first so the audit sees it before the result.

## Needs the owner

- A cTrader **demo account**: open one at IC Markets (cTrader platform) in a browser, then
  re-run the cTrader OAuth consent and tick the demo account so the token can reach it. Then
  set `DEMO_ACCOUNT_ID` (the ctidTraderAccountId, from `python -m scripts.accounts`) in `.env`.
  No API can do this step.
- Databricks sign-in on the PC (daily snapshot upload).
