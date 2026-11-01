# E16 pre-registration: the forward scoreboard (one model, 64 instruments, every hour)

**Status: registered 1 November 2026, committed and pushed before the model or the scoreboard
code exists.** Programme P2, sixth slot. Owner said "Yes" on 2026-11-01 to: a combined model
over many weak signals and all instruments, a locked hourly prediction record as the evidence
for adding capital, an AI news reader as a later signal, and a capital ladder he signs.

## Why this is different from E13 to E15

Those tested single rules on past data, and the past data is used up (the vault has been
opened three times). This experiment is judged **only on predictions made from now on**, each
locked before its hour happens. Nothing about the future can leak into it, so it needs no
vault and no correction for how many rules were tried in the past.

## What runs every hour (just after the hour, UTC)

1. **Snapshot.** One cTrader session reads the live bid and ask of every instrument in the
   universe (the 64 with daily history in `data/market.db`) and refreshes their hourly bars.
2. **Resolve.** Every prediction made one hour earlier is scored against the new snapshot:
   the realised move is mid to mid; the paper trade (below) fills at the real ask or bid of
   both snapshots, so the live spread at that hour is paid.
3. **Predict.** The current model predicts, for each instrument with a fresh quote, the move
   from this snapshot's mid to the next snapshot's mid, in units of that instrument's own
   recent hourly volatility.
4. **Lock.** Each prediction is written to an append-only ledger. Each line carries the SHA-256
   of the previous line, so changing any old line breaks every line after it. The newest hash
   is published to Supabase each hour, which stamps it with the server's own time; a line
   cannot be added later without the published chain disagreeing.

## The model (version 1, fixed here; later versions are new lines on the same scoreboard)

* Gradient-boosted trees (XGBoost), one model pooled over all instruments.
* Inputs per instrument and hour, from hourly bars only: past returns over 1, 4, 24 and 120
  hours, each divided by 24-hour volatility; 24-hour and 120-hour volatility; distance of price
  from its 24 h and 120 h average; hour of the New York day and day of the week; whether today
  is a US jobs, US inflation or Fed day (`data/releases.json`, `data/fomc_dates.json`); the
  instrument's asset class; and the same past returns ranked across all instruments that hour.
* Target: next-hour close-to-close return divided by 24-hour volatility.
* Trained on all hourly history up to the Sunday before it goes live; retrained every Sunday
  on everything to date. Each retrain gets a new file hash, written into every prediction it
  makes.

## Scores (computed only on resolved forward predictions)

* **Skill:** each hour, the rank correlation (Spearman) across instruments between predicted
  and realised move: the information coefficient (IC). The scoreboard shows the running mean
  IC, hit rate (sign right), and the mSPRT always-valid p-value for "mean IC > 0"
  (`learning/stats.py`).
* **Paper book:** each hour, for every instrument whose predicted move is larger than its live
  spread at the snapshot, a paper trade on the predicted side, closed at the next snapshot, net
  of both snapshots' real bid and ask. P&L in bps of notional, equal weight. Never an order.

## Pass criteria (the first rung of the capital ladder)

Checked at any time after **4 weeks and 400 resolved hours** (always-valid tests allow
looking every day without inflating the error):

1. mSPRT p-value for mean hourly IC > 0 below 0.05.
2. Paper book mean hourly net P&L > 0 with mSPRT p-value below 0.05.

Both: rung 1 passed; the owner's signed ladder decides what money follows. Paper book alone
without IC, or IC alone without a positive paper book, is not a pass (skill that does not pay
the spread is not profit). After 12 weeks without a pass, version 1 is recorded FAIL.

## Trials counted

1 (this experiment). Each later model version on the scoreboard is a further trial, and the
pass threshold is then Holm-corrected over the versions running.

## What would make me wrong

* Snapshots a few seconds apart in a fast market are not an executable fill; slippage beyond
  the quoted spread is not modelled. A pass must be confirmed by small real trades.
* Hourly moves are mostly noise; a true IC of 0.02 needs many weeks to show. The most likely
  honest outcome after 4 weeks is "not yet", not "pass".
* If the PC is off, hours are missed. Missed hours are counted and shown, never backfilled.

## Addendum, 1 November 2026, before the first live prediction

At the owner's question about the approaches big firms use, three simple players run beside
the XGBoost blend on the same scoreboard, each locked and scored identically
(`forecast/players.py`): **trend** (slope x 24-hour return), **reversion** (slope x last-hour
return), **regime** (trend when 24-hour volatility is below 120-hour volatility, else
reversion). Each slope is one least-squares number fitted on the same history as the blend.
Trials are now 4. A player passes only if both criteria hold at a Holm-corrected level over the
4 players. Diagnostic before going live (train before 2025, score 2025 to 2026-09 on bar
closes, not judged): the blend's mean hourly IC was 0.048, positive in 55% of hours. Bar closes
can show a bounce between bid and ask that no one can trade, so this says nothing about profit;
the paper book at live spreads is what decides.

## Addendum 2, 1 November 2026, 09:00 UTC: version 2 replaces version 1 before any hour is scored

The independent check found that version 1 learned from bar CLOSES while the live scoreboard
measures from snapshot to snapshot, taken a minute after the hour. Version 2 learns and predicts
the same interval it is scored on: from this hour's opening price (live: the snapshot's bid; bars
are bid prices) to the next hour's. Volatility now skips the jump across a closed market.
Version 1 made predictions for one hour (2026-11-01 08:00 UTC, 32 lines, still in the record) and
is retired unjudged; its 4 players count as trials (E16 trials 8). Only version 2's players are
judged, Holm over the 4 running. Diagnostic on 2025 to 2026-09 bars, not judged: blend IC 0.0545
(FX 0.064, indices 0.014, metals 0.042); trend IC -0.031; reversion 0.047. Bid-only bars can still
show a bounce no one can trade; the paper book at live bid and ask decides.
