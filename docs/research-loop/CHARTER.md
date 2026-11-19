# Research loop charter (set 2026-11-19)

A headless Claude run starts once a day on branch `research/lab` in its own worktree
(`/mnt/n/code/trading/tre-research`). The live engine (`trading-research-engine`, branch it runs
from, systemd `trading-engine.service`) keeps monitoring and is never touched by this loop.

Goal: find a strategy that makes money after all costs on a venue we can actually trade, and
show it with numbers, not opinion.

## Rules (binding on every run)
1. **Empirical only.** Every claim in the journal carries a number from a run in this repo
   (script path + commit) or a cited source (URL). Opinions are labelled "hypothesis".
2. **One experiment per day, finished.** Pick the top `ready` item in AGENDA.md, run it to a
   verdict or to a clearly stated blocker, write the journal, commit. Small and finished beats
   big and half-done.
3. **Pre-register before testing.** Hypothesis, data, window, trial count, pass rule written
   and committed BEFORE results are computed. Every variant run counts as a trial; record the
   count in AGENDA.md and docs/programme/register.json when it becomes a real experiment.
4. **The vault stays sealed.** Development uses data before the holdout start
   (scripts/train_zoo.HOLDOUT_START). Opening the vault is a once-per-shortlist event logged in
   research/vault.py, and only with a pre-registered shortlist.
5. **Cost gate first.** Price the candidate on its target venue (docs/research-loop/VENUES.md)
   before any fit. Reject if expected gross edge < 3x cost. Never plan multi-week CFD holds on
   cTrader (financing; see docs/results/e19-scoping-2026-11-19.md).
6. **Fable red-teams.** Before committing a pre-registration, spawn an Agent with
   model "fable" and give it the spec, data and cost model (not your conclusion); fix or record
   what it finds.
7. **No money moves.** No orders, no edits to risk limits, the capital ceiling, the live
   service, forecast/, news/ or forecast/judge.py. Paper only. Anything ready for real money is
   proposed to the owner by email.
8. **Light compute.** Daily bars or smaller samples, `nice`, at most 4 threads, no load bursts.
   Run under 2.5 hours.
9. **Honest outcomes.** A FAIL is a result; record it in the journal and the agenda with its
   failure mode (NO_PREDICTIVE_EDGE, EDGE_DESTROYED_BY_COSTS, ..._BY_FINANCING,
   NOT_DISTINGUISHABLE_FROM_LUCK, DATA_NOT_TRUSTWORTHY).
10. **Report.** Email the owner (Gmail tool, to his own address) only when: a verdict lands, a
    blocker needs him, or every Sunday a 5-line weekly digest. Plain words, no jargon, no dashes.
