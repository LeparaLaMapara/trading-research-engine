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

## What the daily run does now

Refreshes the account snapshot and the bar history, then runs the self-audit. It no longer tests
strategies, so it no longer inflates N.

## Status

`python -m research.programme` prints the budget, what has been spent and what passed.
