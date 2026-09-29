# The research programme, from 22 September 2026

## Why this replaced the daily search

Until 22 September the daily run re-tested the same five textbook strategies on the same three
symbols. They failed every day. Worse than useless: every test raises the bar a real idea has to
clear later, because the deflated Sharpe is corrected for how many things were tried. The search
was spending the budget of future discoveries on repeats.

The evidence also said where not to look. Of 20 candidates classified on 20 September, 14 had a
real edge before costs that costs removed, and the largest cost at this broker is the overnight
financing charge. The venue re-score and its pre-registered holdout (falsified) showed that
changing venue alone does not rescue the signals we hold.

## The rules

1. **Budget: 10 experiments.** Counted from 22 September 2026. Each one is listed in
   `register.json`.
2. **Pre-register first.** Each experiment has a pre-registration document, committed and pushed
   BEFORE its result exists. It states the hypothesis, the exact rule, the data, the costs and
   the pass criteria. `ops/audit.py` checks the commit order from git history, so this cannot be
   done after the fact without leaving evidence.
3. **One hypothesis per slot.** Variants tested inside one experiment are declared in its
   pre-registration and all counted in N.
4. **A pass is not a trade.** Passing makes a strategy a candidate for demo paper trading. A
   live order still needs the engine's deflated Sharpe bar (0.95) and the owner's signed grant.
5. **The stop rule.** If all 10 experiments are spent and none passes, the conclusion is written
   down: this account, at this broker, has no edge worth trading. The project then continues as a
   measurement lab (what retail trading really costs), not as a money maker. The audit reports
   this as a failing check so it cannot be missed.
6. **Where ideas come from.** Published results with a resolvable citation, and the engine's own
   cost measurements. The language model council proposed 33 daily candidates and was right
   about its own proposals 46% of the time, worse than a coin. It builds and checks code; it no
   longer picks strategies.

## Where ideas come from now: the reading room (from 29 September 2026)

Reading and testing are kept apart. Testing spends a slot and raises N; reading does neither.

Every Sunday `scout/reading_room.py` (workflow `reading.yml`) harvests the last two weeks of
papers from arXiv and OpenAlex across quantitative finance, economics, statistics,
mathematics, physics, computer science and mathematical economics, plus one theme of older,
well-cited foundations. A model scores every abstract, reads the best eight in full, and writes
an idea card: the concept, its market analogue, a falsifiable hypothesis on instruments this
account can trade, and the cheapest honest test. Code checks every quote against the fetched
text; a card without verified quotes is never queued. A second, adversarial read tries to kill
each card against `docs/research/engine-facts.md` and the results above, and scores it. Code
ranks the queue (`docs/research/queue.json`) by information x value / cost and writes the
week's memo to `docs/research/weekly/`.

Nothing in the queue is a test. A slot is spent only by writing a pre-registration from the top
of the queue, as before. Spend is capped at 6 US dollars a run, checked before every call.

## Renewal, the running N, and audits (owner-approved 29 September 2026)

More experiments are allowed; an easier bar is not.

1. **Budgets renew.** When a programme has spent its whole budget, a new programme of 10 may
   open (P2, P3, ...) by adding it to `programmes` in `register.json`. It may not open earlier.
   The stop rule applies to each programme: 10 spent with no strategy pass means that programme
   found no edge worth trading.
2. **N never resets.** `n_before_programme` (295, the candidates documented by 19 September)
   plus every experiment's `trials` is the running N. Every new result reports its deflated
   Sharpe at that N or more, and a live rule needs the deflated Sharpe bar at that N.
   `python -m research.programme` prints the current N. Correction made the same day: E03
   was left out of the count E05 to E08 used, so their N was one too low; N is now 306.
3. **Audits spend no slot.** An audit (`kind: audit`, id `Axx`, field `audits`: the experiment
   it re-tests) runs a rule that is already counted through stronger methods: more null
   draws, block bootstrap intervals, the current N, measured costs. It adds no trials, because
   it tests nothing new. It can only demote: a failed audit takes the rule out of live trading;
   a passed audit changes nothing. It is pre-registered and committed first, like everything
   else.
4. **Computation is not the limit.** Heavy runs go to Databricks (`databricks-run.yml`), which
   makes stronger tests affordable. It does not make more tests honest; only rules 1 to 3 do.

## What the daily run does now

Refreshes the account snapshot and the bar history, then runs the self-audit. It no longer tests
strategies, so it no longer inflates N.

## Status

`python -m research.programme` prints the budget, what has been spent and what passed.
