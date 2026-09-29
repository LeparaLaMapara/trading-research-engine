# E08 result: the live trend rule on five affordable currency pairs. PASS on USDSGD only, and thinly

Run on 29 September 2026 after the pre-registration (c9aa22a) was pushed. Raw numbers:
`E08-fx-trend.json`. Re-run with `python -m scripts.e08_fx_trend`.

## Result

| pair | net Sharpe | gross | costs doubled | today's full swap | years positive | verdict |
|---|---|---|---|---|---|---|
| USDSGD | **0.15** | 0.56 | 0.006 | 0.13 | 7 of 11 | **PASS** |
| AUDNZD | -0.06 | 0.24 | -0.23 | -0.05 | 3 of 11 | FAIL |
| EURGBP | -0.46 | -0.25 | -0.50 | -0.46 | 3 of 11 | FAIL |
| EURCAD | -0.55 | -0.30 | -0.71 | -0.55 | 4 of 11 | FAIL |
| AUDCAD | -0.70 | -0.42 | -0.87 | -0.70 | 3 of 11 | FAIL |

Three of five lose money even before costs: the 20-day trend does not work on most currency
crosses, which agrees with the 23-year trend test of 19 September.

## How much to trust the USDSGD pass

Not much, and the numbers say why:

* **Deflated Sharpe at N = 305 is 0.009.** After counting every rule this project has tried, a
  result this size is what luck produces. It passes the pre-registered criteria, but they do
  not include the deflated Sharpe.
* **C2 was an easy bar.** The random-sign null pays the same costs and financing on hundreds of
  round trips, so its 99th percentile (-0.38) sits below zero. The binding criterion was C1.
* **It survives doubled costs by 0.006.** Costs decide it.

## The cost question, checked after the verdict (not part of the pass)

There is no recorded tick data for USDSGD, so `measured_cost` assumed 2 bps of price
(2.55 pips). Five live quotes at 14:10 UTC on 29 September showed spreads of 0.1 to 0.9 pips,
so the assumption is conservative **at that hour**. But the live trader decides once per
completed daily bar, and broker daily bars close at 21:00 UTC, the rollover, when spreads on
this account were measured at about ten times their afternoon level. Traded at the rollover,
USDSGD would likely pay more than twice the assumed cost, and at twice the cost the edge is
gone.

## What changes

* Per the pre-registration, USDSGD becomes a live candidate beside Ethereum.
* **Condition added before it trades, from the evidence above:** USDSGD orders must be sent
  away from the rollover (not between 20:00 and 23:00 UTC), and its spread must be recorded
  so the cost is measured, not assumed. This is an execution rule, not a change to the tested
  signal.
* AUDCAD, AUDNZD, EURCAD and EURGBP are not traded.

## Budget

8 of 10 spent. Strategy passes: E05, E07, E08 (USDSGD, weak). E04 passed as a measurement.
