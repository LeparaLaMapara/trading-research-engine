# E04 pre-registration: what a real fill costs, measured on the live account

Written and committed on 22 September 2026, BEFORE any probe is sent. Experiment 4 of 10. The
owner authorised it the same day ("Cost-measurement trades": up to 20 of the smallest possible
trades, opened and closed within seconds, grant capped at R540 for 7 days, the position limit
raised to 2 while the ETHUSD trade is open).

## Why

Every backtest in this engine assumes a market order fills at the quoted price, so the only
trading cost is the spread plus commission. Slippage has never been measured: one probe on
15 September recorded the entry but not the exit. If fills are worse than the quote, every
backtest has understated its costs, and every future experiment inherits the error.

## Protocol

* `python -m scripts.probe --allow-live --confirm`, EURUSD, 0.01 lots (the broker minimum),
  opened at market and closed at market within seconds.
* 20 round trips, alternating BUY and SELL starting with BUY, at least 60 seconds apart.
* Each probe passes the owner's signed grant and the plain-code risk officer.
* Entry slippage is measured against the quote live when the order was sent; exit slippage
  against the quote live when the close was sent. Both signed so that positive is worse for us.
  Latency from send to fill is recorded for each leg.
* **Stops early** if equity falls below $27 (total cost capped at about $3), if any probe fails
  to close, or if the broker rejects two orders in a row.
* Only trade log rows with trade_id above 13 (the last row before this experiment) count.
* Disclosure: run in the evening, SAST (about 19:00 to 20:00 UTC), outside the London and New
  York overlap. The result speaks for that hour, not for all hours.

## Pass criteria (both required)

The hypothesis is that the backtest cost model is not materially wrong.

* **C1**: mean adverse slippage per leg is at most 0.1 pip.
* **C2**: mean net cost per round trip (from the balance change) is at most 1.25 times the
  modelled cost (the spread at send, plus two sides of commission).

## What each outcome means

* PASS: backtests may keep assuming fills at the quote, for EURUSD at this size.
* FAIL: backtests understate costs. The measured slippage is added to `backtest/run.py`'s cost
  model before any further experiment is scored.

Either way the grant is revoked when the probes finish.

## Counting

Counts as one slot of the 10. It is not a strategy, so it adds nothing to the deflated-Sharpe N.
