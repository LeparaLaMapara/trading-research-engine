# E07 result: the Ethereum trend rule without a profit target. PASS, and it replaces E05

Run on 23 September 2026 after the pre-registration (efc4781) and the code were pushed. Raw
numbers: `E07-no-target.json`. Re-run with `python -m scripts.e07_no_target`.

## Result

| criterion | needed | got | |
|---|---|---|---|
| C1 net Sharpe | above 0 | 0.80 | pass |
| C2 beat the random-sign null | above 0.27 | 0.80 | pass |
| C3 years positive | 5 of 8 (2018 to 2025) | 6 of 8 | pass |
| C4 net Sharpe at double costs | above 0 | 0.75 | pass |
| C5 beat E05 on the same data | above 0.58 | 0.80 | pass |

276 round trips in nine years instead of E05's 509, held 9.3 days on average; the largest
single trade returned +153%. The target was cutting off exactly the long runs that pay a trend
rule, and doubled costs barely matter because it trades half as often.

## How much weight it carries

* Deflated Sharpe at N = 300 is 0.22: stronger than E05 (0.09), still well short of proof.
* 2023 and 2024 still lost. Without a target, a winning trade gives back more before its stop.
* It is a variant of a rule that had already passed, on the same data, so some of the
  improvement may be luck in choosing the variant. It is counted in N for that reason.

## What changed live

From 23 September 2026 new engine trades carry a stop and no target (`scripts/trader_step.py`
passes `--no-target`; `scripts/rehearsal.py` now requires a target only when the rule sets one,
since it would otherwise have closed a stop-only position as "unprotected"). The position open
when E07 passed (0.03 ETH, target 3019.82) keeps its target, as the pre-registration said.

## Budget

7 of 10 spent. 2 strategies passed (E05, E07; E07 is live). E04 passed as a measurement.
E03 is recording.
