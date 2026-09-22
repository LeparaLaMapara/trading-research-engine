# E05 result, Part A (history): Ethereum 20-day trend. PASS

Run on 23 September 2026 after the pre-registration (cf76cc5) and the code (committed before
the run) were pushed. Raw numbers: `E05-eth-trend.json`. Re-run with
`python -m scripts.e05_eth_trend`.

## What was tested

Long ETHUSD when its last 20 days were up, short when down, one position at a time, entered at
the next day's open with a 2-sigma stop and a 1.5R target at the broker, 20% a year financing on
longs, 11.9 bps per round trip (today's measured spread as a fraction of price, plus
commission). October 2017 to September 2026: 2,582 days, 509 round trips.

## Result

| criterion | needed | got | |
|---|---|---|---|
| C1 net Sharpe | above 0 | 0.58 | pass |
| C2 beat the random-sign null | above 0.29 | 0.58 | pass |
| C3 years positive | 5 of 8 (2018 to 2025) | 6 of 8 | pass |
| C4 net Sharpe at double costs | above 0 | 0.48 | pass |

The first strategy in the programme to pass. Gross Sharpe 0.68, so costs take little: this
rule trades about once a week, not every day.

## How much weight it carries

* Corrected for the 298 things this engine has tried, the evidence is weak: deflated Sharpe
  0.09, far under the 0.95 the engine used to require before a live trade. It passed its own
  pre-registered test; it has not proven an edge beyond doubt.
* The two losing years are the two before last (2023, 2024). A trend rule loses in markets that
  chop sideways, and those can last a year.
* The effect is published and well known (Liu and Tsyvinski 2021), which is reassuring about
  it being real and a reason to expect it to be weaker than in the past.
* In money, at the only size this account can trade (0.01 ETH, about $27 of exposure), the
  history implies roughly $10 a year, with losing months common. The rule is the same at any
  size; the rand amount grows with the account.

## Part B

Live trading of this rule starts on 23 September 2026 under the owner's standing instruction.
After 20 live round trips the live results are compared with this history.

## Budget

4 of 10 spent. 1 strategy passed (E05). E04 passed as a measurement.
