# Live check: are the live rules still the rules their backtests described?

Written 2026-09-30T00:29:49Z by `research/live_check.py`. The rules are in that file's docstring and were fixed before any live data arrived.

| instrument | test | assumed cost | measured cost (median, p90) | quotes, hours | cost | live opens vs backtest pace |
|---|---|---|---|---|---|---|
| ETHUSD | E07 | 11.9 bps | 12.21, 13.11 bps | 14930, 6 | **WARN** | 2 in 7.0 days vs 0.8 (too early to judge) |
| USDSGD | E08 | 2.7 bps | 1.09, 1.4 bps | 773, 6 | **OK** | 1 in 0.3 days vs 0.0 (too early to judge) |

Reasons:

* ETHUSD: measured 12.21 bps is above the assumed 11.90 bps
* USDSGD: measured 1.09 bps is within the assumed 2.70 bps
