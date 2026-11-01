# E13 pre-registration: search every hourly window, then open the vault once

**Status: registered 1 November 2026, committed and pushed before any search code exists.**
Programme P2, third slot. Design: `docs/plans/discovery-machine-2026-11.md`.

## The idea in plain words

Instead of testing one published idea at a time on all the data, try every simple intraday
clock rule on the older years only (the search room), pick a short list, and test the short
list once on years the search never saw (the vault). Survivors go to paper trading on live
quotes, never straight to money.

## Data

* Dukascopy hourly bid AND ask bars, 2014-01-01 to 2026-09-30, for EURUSD, GBPUSD, AUDUSD,
  NZDUSD, USDJPY, USDCHF, USDCAD (`T:\making-money\features\intraday\h1`, the same files as
  E12; SHA-256s in the result).
* Fill at the OPEN of the hourly bar starting at the entry or exit hour: buy at the ask, sell
  at the bid. Commission 0.35 bps of notional per side. A trade is dropped if a fill bar is
  missing, crossed, or has a spread over 5 bps.

## The rule space (fixed here)

The trading day runs from 18:00 New York (after the rollover) to 16:00 New York next day:
22 hourly slots, offsets 0 to 21. A rule is:

* instrument: one of the 7;
* entry offset e in 0..21 and hold k in {1, 2, 3, 4, 6, 8} hours with e + k <= 22, so every
  trade is flat by 16:00 New York and never crosses the rollover (no financing);
* direction: buy or sell the pair;
* weekday filter: all days, or one of Monday..Friday (the weekday of the 16:00 close);
* prior filter: none, or only when the pair rose (fell) over the previous 24 hours, measured
  mid to mid from the entry bar's open 24 hours earlier to the entry bar's open.

Every combination is evaluated. All are counted in N.

## Samples

* Search room: trading days closing 2014-01-02 to 2022-12-30.
* Vault: trading days closing 2023-01-02 to 2026-09-30. `research/vault.py` refuses to return
  vault returns unless it is given the short list, and appends the list's hash and the time to
  `docs/results/vault-log.jsonl`. A second opening for E13 is refused.

## Selecting the short list (search room only)

1. Daily net return per rule (0 on days the filter is off; days a fill is dropped are skipped).
2. Eligible: at least 200 trades, mean net per trade >= 0.5 bps, positive net return in at
   least 6 of the 9 search years.
3. Rank by net t-statistic per trade. Walk down the ranking and keep a rule unless its daily
   return series correlates above 0.3 with one already kept. Stop at 10.

## Pass criteria (vault, per short-listed rule)

1. Net mean per trade > 0 with one-sided p below its Holm-Bonferroni threshold across the 10
   (family-wise 5%).
2. Net mean per trade > 0 with spread and commission both multiplied by 1.5.
3. Positive net return in at least 3 of the 4 vault years (2026 partial).

A rule passing all three becomes a **forward paper candidate**. Not a live order.

Reported, not deciding: deflated Sharpe at the programme's running N plus the full rule count,
and the vault result of every short-listed rule.

## Trials counted

Every rule evaluated in the search room, 28,728 (7 x 114 windows x 2 directions x 6 weekday filters x 3 prior filters), counted in N.

## Proposed rule for the forward stage (for the owner's record)

A forward candidate earns a live slot when the mSPRT on its live paper trades says "edge > 0"
at 5%, corrected for the number of candidates running forward, and its paper results net of
the broker's measured live spread stay positive. The global-N deflated Sharpe of 0.95 (rule 4)
cannot be met by any search of this size from backtest alone; the vault and forward stages are
what replace it. Until the owner reads this, rule 4 stands.

## What would make me wrong

* The vault is partly seen (E10 time of day on H1 2015-2026; E11, E12 on 2020-2026). A pass
  could be luck that leaked through; the forward stage exists for this.
* No stop is simulated and the news blackout is not applied.
* Most likely result: zero passes. Clock patterns this simple are the first thing every bank
  desk looks at. If so, the result still tells us something: there is no hourly clock edge
  left in majors at retail cost, and the next search moves to events (data releases, month end)
  or to other instruments.
</content>
</invoke>
