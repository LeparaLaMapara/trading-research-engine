# Research loop charter (set 2026-11-19)

A headless Claude run starts once a day, inside a bwrap wall (live secrets and broker credentials
hidden, live checkout read-only; see ops/research_loop/run.sh), on branch `research/lab` in its own worktree
(`/mnt/n/code/trading/tre-research`). The live engine (`trading-research-engine`, branch it runs
from, systemd `trading-engine.service`) keeps monitoring and is never touched by this loop.

Goal: find a strategy that makes money after all costs on a venue we can actually trade, and
show it with numbers, not opinion.

## Rules (binding on every run)
1. **Empirical only.** Every claim in the journal carries a number from a run in this repo
   (script path + commit) or a cited source (URL). Opinions are labelled "hypothesis".
2. **One unit of work per day, finished.** Pick the top `ready` agenda item and finish it:
   a cost table, a data check, a pre-registration, a scoping run, or ONE pre-registered test.
   Small and finished beats big and half-done. This loop is not a daily search: the programme
   rules in docs/programme/README.md and CLAUDE.md bind it.
3. **Pre-register before testing, a day ahead.** A counted test runs only against a
   pre-registration that was committed and PUSHED in an earlier run and entered in
   docs/programme/register.json (it spends one of the programme's slots; P2 had 3 left on
   2026-11-19, check `python -m research.programme`). Any run that prints performance on
   development data counts as trials: write the count in the journal and fold it into the next
   pre-registration's N. Never pick a rule because it scored best in a scoping run without
   counting that choice. Run `python -m ops.audit` and `pytest -q` before pushing code.
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

11. **The repo is PUBLIC.** No balances, account sizes, personal details, emails or employer
    names in anything committed. Private notes go to ~/.config/trading-research-loop/.
