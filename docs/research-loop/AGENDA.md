# Research agenda (ranked; the daily run takes the top `ready` item)

Status: ready | running | blocked (why) | done (verdict, trials) | dropped (why)
Priority = information x value / cost (1-5 each). Re-rank when evidence changes; say why.

| # | item | venue | prio | status |
|---|---|---|---|---|
| - | E19 cost split for ewmac, breakout, blend; by class and era. | futures | | done 2026-11-19: CFD financing 1.5x to 3.2x gross for every rule; spread only net tsmom 0.25, blend 0.14, ewmac 0.08, breakout 0.03 (fails cost gate, EDGE_DESTROYED_BY_COSTS). Post-2017 ~0 except metals, bonds. 4 trials. docs/results/e19-cost-split-2026-11-19.md |
| 1 | Build VENUES.md cost model: IBKR micro futures (commission, exchange fee, roll cost per quarter, margin per contract), EasyEquities JSE ETF/share (brokerage, VAT, levies, STT), cTrader CFD (measured spread, financing). Each number cited. Rank up: E19 needs real futures costs; the CFD spread proxy puts ewmac and blend right on the 3x cost line. | all | 45 | ready |
| 2 | Pre-register E19: slow diversified trend (tsmom_12m family, turnover <= ~15/yr; breakout excluded, fails cost gate) on a futures cost model, daily bars, Dukascopy 2004 to holdout. Universe fixed a priori by available micro futures, NOT by the class split of 11-19. Count the 4 scoping trials. Fable red-team. | IBKR futures (paper) | 38 | ready (after 1) |
| 3 | Monthly ETF allocation for the EasyEquities pool: time-series trend filter / risk parity on JSE-listed ETFs vs buy-and-hold Satrix 40 / global equity. Hand-executed monthly. Data: yfinance .JO (from 2000, dividends adjusted; current listings only, fine for ETFs/indices, NOT for stock picking). Costs: EasyEquities ~0.25% brokerage + 0.0795% settlement + VAT per side; ETFs exempt from STT (STT Act s8(1)(f), verify per fund); TFSA holds ETFs only. Unlevered, no financing: the venue where slow trend is not killed by carry costs. | EasyEquities | 34 | ready |
| 4 | E18 SENS announcements. | JSE (manual) | 30 | blocked: no free licensed SENS archive or feed (Sharenet terms forbid reuse, JSE disallows AI crawlers; data check 2026-11-19). Revisit only with a broker feed or owner-approved paid feed. |
| 5 | Strategy families from the Fable review 2026-11-19 (to be added). | | | pending |

Dropped: hourly FX prediction, crypto order-book signals, intraday clock windows (E01-E03, E13-E15 FAIL).
