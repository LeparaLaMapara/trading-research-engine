# Research agenda (ranked; the daily run takes the top `ready` item)

Status: ready | running | blocked (why) | done (verdict, trials) | dropped (why)
Priority = information x value / cost (1-5 each). Re-rank when evidence changes; say why.

| # | item | venue | prio | status |
|---|---|---|---|---|
| 1 | Fix the ewmac zero-output in lab/e19/cost_split.py; re-run spread-only split for ewmac, breakout, blend; split by asset class and by era. Scoping only, pre-holdout. | futures | 45 | ready |
| 2 | Build VENUES.md cost model: IBKR micro futures (commission, exchange fee, roll cost per quarter, margin per contract), EasyEquities JSE ETF/share (brokerage, VAT, levies, STT), cTrader CFD (measured spread, financing). Each number cited. | all | 40 | ready |
| 3 | Pre-register E19: diversified trend (+ carry if data allows) on a futures cost model, daily bars, Dukascopy 2004 to holdout; minimum capital at micro-futures sizes; Fable red-team. | IBKR futures (paper) | 36 | ready |
| 4 | Monthly ETF allocation for the EasyEquities pool: time-series trend filter / risk parity on JSE-listed ETFs vs buy-and-hold Satrix 40 / global equity. Hand-executed monthly. Data: yfinance .JO (from 2000, dividends adjusted; current listings only, fine for ETFs/indices, NOT for stock picking). Costs: EasyEquities ~0.25% brokerage + 0.0795% settlement + VAT per side; ETFs exempt from STT (STT Act s8(1)(f), verify per fund); TFSA holds ETFs only. | EasyEquities | 32 | ready |
| 5 | E18 SENS announcements. | JSE (manual) | 30 | blocked: no free licensed SENS archive or feed (Sharenet terms forbid reuse, JSE disallows AI crawlers; data check 2026-11-19). Revisit only with a broker feed or owner-approved paid feed. |
| 6 | Strategy families from the Fable review 2026-11-19 (to be added). | | | pending |

Dropped: hourly FX prediction, crypto order-book signals, intraday clock windows (E01-E03, E13-E15 FAIL).
