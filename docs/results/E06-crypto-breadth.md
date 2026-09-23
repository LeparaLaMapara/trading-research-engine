# E06 result: E05's rule across eight coins, combined. FAIL, with a useful finding

Run on 23 September 2026 after the pre-registration (fa608d3) and the code were pushed. Raw
numbers: `E06-crypto-breadth.json`. Re-run with `python -m scripts.e06_breadth`.

## Result

| criterion | needed | got | |
|---|---|---|---|
| C1 beat the random-sign null | above -0.30 | 0.46 | pass |
| C2 breadth beats Ethereum alone | above 0.52 | 0.46 | **fail** |
| C3 years positive | 6 of 8 (2018 to 2025) | 5 of 8 | **fail** |
| C4 net Sharpe at double costs | above 0 | 0.28 | pass |

Each coin alone: ETH 0.52, BTC 0.49, DOT 0.40, SOL 0.31, BCH 0.07, XRP 0.07, LTC -0.27,
ADA -0.72.

## What it means

**Breadth works; averaging good edges with bad ones does not.**

* The coins' rule returns are far less alike than their prices: average correlation 0.37, worth
  about **4.1 independent bets** out of 8. The owner's intuition holds: the combination (0.46)
  is about four times the average single coin (0.11).
* It did not beat Ethereum alone, because equal-risk weighting gives the same slice to coins
  with no edge. ADA costs 122 bps a round trip (its spread is a p75 hedge from three hours of
  recording) and loses; LTC loses; BCH and XRP add little.
* ETH was not picked as the best coin. E05 chose it because it was the one instrument the
  account could afford. So C2 compared the portfolio against the best coin by luck, and it
  still came close.

## What changes

* The live engine stays on Ethereum alone. E06 does not justify spreading the account across
  coins.
* The lesson for the remaining four experiments: breadth must be built from components that
  each have their own evidence and low cost. Choosing only coins that passed individually would
  be selection after the fact on these same data, so it cannot be tested here; it needs data
  not yet seen or a pre-registered rule for admission.

## Budget

6 of 10 spent. 1 strategy passed (E05). E04 passed as a measurement. E03 is recording.
