# E15 pre-registration: every hourly window on Bitcoin and Ethereum, the same machine as E13

**Status: registered 1 November 2026, committed and pushed before any scoring code exists.**
Programme P2, fifth slot. Machine: `docs/plans/discovery-machine-2026-11.md`. E13 and E14 found
no clock or event edge in the FX majors. Crypto trades around the clock, is younger and less
arbitraged, and this broker quotes it at weekends.

## Data

* Binance spot hourly klines, BTCUSDT and ETHUSDT, 2017-08-17 to 2026-09-30
  (`scripts/fetch_binance_h1.py` -> `T:\making-money\features\intraday\crypto_h1`, SHA-256s in
  the result). The open of each hourly bar is the price. Missing hours (28 exchange gaps) drop
  the trades that need them.
* Exchange prices have no bid/ask, so the broker's measured spread is laid around the open:
  the 95th percentile of every BTCUSD and ETHUSD tick in `data/telemetry.db` (16 to 20 Sep
  2026): **BTCUSD 4.82 bps, ETHUSD 12.42 bps** round trip. Plus 0.35 bps commission a side (the
  broker charges none on crypto; kept to match E13). Only 6 hours of the week were observed, so
  these may understate night and weekend spreads; criterion 2 stresses them by 1.5x.
* Financing: none, because every trade is flat by 16:00 New York, before the broker's rollover.

## Rule space (fixed here)

Exactly E13's: trading day 18:00 New York to 16:00 next day, entry offset e and hold k in
{1, 2, 3, 4, 6, 8} hours with e + k <= 22 (114 windows), buy or sell, prior filter none / rose
over 24 h / fell over 24 h, and a day filter of every day or one of the **seven** days (crypto
trades weekends). 2 x 114 x 2 x 8 x 3 = **10,944 rules**, all counted in N. Days are every
calendar day.

## Samples

Search room: closing days 2017-08-18 to 2022-12-31. Vault: 2023-01-01 to 2026-09-30
(`research/vault.py`, opened once for E15).

## Short list (search room only)

Eligible: at least 200 trades, mean net per trade >= 1.0 bps, positive net in at least 4 of the
6 search years (2017 partial). Rank by net t per trade; keep a rule unless its daily series
correlates above 0.3 with one already kept; stop at 10.

## Pass criteria (vault, per short-listed rule)

As E13: Holm-Bonferroni family-wise 5% over the 10; positive at 1.5x spread and commission;
positive in at least 3 of the 4 vault years. A pass is a forward paper candidate under
programme rule 4 (owner approved 2026-11-01).

## Can the account trade it

Reported, not deciding. ETHUSD minimum is 0.01 ETH (about $25 of notional): fits easily, small
money. BTCUSD minimum is 0.01 BTC (about $1,000): a stop wider than about 0.5% would break the
6% limit at $79.

## What would make me wrong

* The cost assumption rests on four days of ticks. A pass would need the live spread measured
  at the rule's own hours before any paper result counts.
* Binance spot is not the broker's price; the broker's CFD feed can lag or differ.
* The vault years have been opened for FX rules (E13, E14) but never for crypto.
