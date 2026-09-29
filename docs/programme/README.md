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

## What the daily run does now

Refreshes the account snapshot and the bar history, then runs the self-audit. It no longer tests
strategies, so it no longer inflates N.

## Status

`python -m research.programme` prints the budget, what has been spent and what passed.
