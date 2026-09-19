# FX carry pre-registration, 2026-09-19

Written before the carry experiment is run.

## Why this experiment, and why now

The zoo scores FX on PRICE returns plus a flat 1% financing charge. A CFD position actually
earns or pays the interest differential between the two currencies, minus the broker markup.
Checked against the broker today: EURUSD swap long -0.82 and short +0.15 points per lot per
day, with EUR 3m at 2.03% and USD at 3.82%, implies a markup of about 0.8 to 1.3% a year. So
the flat 1% is the markup; the differential itself was missing from every FX result.

Carry is also among the most documented FX effects (Lustig and Verdelhan 2007; Burnside et al.
2011; Koijen, Moskowitz, Pedersen and Vrugt 2018, "Carry", JFE). It was never tested here
because no point in time rate history was held. That was DATA_FAILURE, not falsified.

## Data

* OECD 3 month interbank rates via FRED, series `IR3TIB01{CC}M156N`, monthly, for US, EZ, GB,
  JP, AU, NZ, CA, CH, NO, SE, PL, MX, ZA. Stored under `T:\making-money\features\rates`.
* Point in time rule: the value for month M is usable only from the first day of month M+2.
  Interest rate data is market data and barely revised; the lag guards against publication
  delay. Forward filled after that. SGD has no series: USDSGD excluded.
* Universe: every panel FX pair whose two currencies both have a series.

## P&L

Price return plus the differential earned by the held side: notional x sign x
(r_base - r_quote) / 260 per bar, minus the 1% markup (already in the cost table). Spread and
commission as in the zoo. Identical buffer and vol scaling.

## Candidates (count towards N)

* `fx_zero_carry_long`: long every pair, differential included (baseline for this universe).
* `carry_ts`: forecast = (r_base - r_quote) / annual vol of the pair, scaled on training data.
* `carry_xs`: centred cross-sectional rank of the differential across pairs each date.
* `carry_trend`: equal average of scaled `carry_ts` and scaled `ewmac`.
* `ewmac_fx_withcarry`: the zoo's ewmac on the same universe, now with the differential in P&L,
  so the comparison is like for like.

## Split and decision rule

Same as the zoo: development 2017-01-01 to 2024-09-15, walk forward by year, holdout from
2024-09-16 touched once for the champion only. PASS needs DSR >= 0.95 against honest N,
positive in at least 5 of 8 development years, and positive holdout.

## Prior

Carry has a long positive record with crash risk (2008). 2017 to 2024 includes zero rate
years for EUR, JPY, CHF that compress the spread. Prior probability of a pass: about 15%.
