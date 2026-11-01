# E14 pre-registration: event days (US jobs, US inflation, month end), the same machine as E13

**Status: registered 1 November 2026, committed and pushed before any scoring code exists.**
Programme P2, fourth slot. Machine: `docs/plans/discovery-machine-2026-11.md`. E13 found no
plain clock edge on all days; this asks whether the dollar behaves predictably on the days
the big US numbers come out, or at month end, when flows are forced.

## Data

* Hourly bid and ask, 7 majors, 2014-01-01 to 2026-09-30: the E13 files.
* US jobs (NFP, series PAYEMS) and US inflation (CPI, series CPIAUCSL) release days from the
  St. Louis Fed's ALFRED vintage archive (`news/releases.py` -> `data/releases.json`): 153 of
  each 2014-01 to 2026-10. A vintage counts only if it adds a new month of data (seasonal
  revisions dropped). Both are released at 08:30 New York.
* Month end: the last weekday of each calendar month; month start: the first weekday.
* Fills, costs, slots and the dropped-trade rule exactly as E13 (slot o is 18:00 New York + o
  hours on the evening before the closing day; 08:00 is slot 14, 16:00 is slot 22).

## Rule space (fixed here)

**A. Reaction rules, NFP and CPI days.** The reaction is the mid move from the 08:00 open to
the r open, r in {09:00, 10:00} (it contains the 08:30 release). At r, trade in the reaction's
direction (follow) or against it (fade); exit at the open of x, every hour from r+1 to 16:00.
Instruments: each of the 7, plus the basket (equal-weight average of the 7 single-pair trades,
each following or fading its own reaction). 2 events x 13 (r, x) pairs x 2 modes x 8 = 416.

**B. Clock rules on event days.** On NFP days, CPI days, month-end days and month-start days:
every E13 window (114 entry/hold pairs, flat by 16:00) x buy or sell x 7 pairs, no other
filter. 4 x 114 x 2 x 7 = 6,384.

Total 6,800 rules, all counted in N.

## Samples

Search room 2014-2022, vault 2023-2026-09 (`research/vault.py`), as E13.

## Short list (search room only)

Eligible: at least 80 trades, mean net per trade >= 1.0 bps, positive net in at least 6 of the
9 search years. Rank by net t per trade; keep a rule unless its daily series correlates above
0.3 with one already kept; stop at 10.

## Pass criteria (vault, per short-listed rule) and what a pass means

As E13: Holm-Bonferroni family-wise 5% over the 10, positive at 1.5x spread and commission,
positive in at least 3 of the 4 vault years. A pass is a forward paper candidate under
programme rule 4 (owner approved 2026-11-01), never a live order by itself.

## What would make me wrong

* About 45 events per type fall in the vault, so only a large effect can pass Holm over 10.
  Expect low power; a FAIL here says "not shown", not "absent".
* The vault has been opened once before (E13). Its results were seen only for E13's 10 rules,
  none of which is in this space (they were all-day or weekday rules). Reusing the vault years
  across experiments leaks a little each time; the forward paper stage exists to catch that.
* Month end is tested as clock windows only. The published month-end dollar effect (Melvin and
  Prins 2015) conditions on equity performance over the month; that needs data the engine does
  not hold intraday and is not attempted.
</content>
</invoke>
