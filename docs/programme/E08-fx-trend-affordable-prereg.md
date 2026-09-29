# E08 pre-registration: the live trend rule on the currency pairs the account can afford

Written and committed on 29 September 2026, BEFORE any of these five instruments is scored with
this rule. Experiment 8 of 10.

## Why this one

The owner asked why the engine trades only one thing. The answer so far: only one rule has
passed (E05, then E07 on Ethereum), and at $28 of equity nothing else fitted the signed limits.

On 29 September every one of the 64 instruments with daily history was dry-run through the live
order path at $85.12 of equity (nothing sent). That run found and fixed two sizing faults
(commit e1441fc: pips valued in the wrong currency, and no step down to a size whose margin
fits). After the fix, 9 instruments fit the limits (6% risk per trade, margin at most 50% of
equity): ETHUSD, ADAUSD, BCHUSD, LTCUSD, AUDCAD, AUDNZD, EURCAD, EURGBP, USDSGD.

ADA, BCH and LTC were already scored with this rule in E06 (net Sharpe -0.72, 0.07, -0.27).
Scoring them again would be repetition, not evidence. That leaves five currency pairs this rule
has never been scored on.

**Admission rule, fixed now:** the five pairs are AUDCAD, AUDNZD, EURCAD, EURGBP, USDSGD, chosen
because they fit the limits today, not because of how they performed. No pair is added or
dropped after the scores are seen.

## The rule

Exactly the live rule (E07, `lab/eth_trend.simulate` with `reward_ratio=None`): once a day, the
sign of the last 20 completed daily returns; long if positive, short if negative; a broker-side
stop at 2 EWMA daily sigmas (span 36); no profit target; exit at the stop or on a signal flip.
Entry at the next day's open; stop checked against each day's low and high.

## Data and costs

* Broker daily bars in `data/market.db`, from the first stored bar (September 2014) to
  2026-09-19, the same cut-off E05 to E07 used.
* Spread: `backtest.run.measured_cost` for each pair, as a fraction of today's price, plus two
  sides of commission (0.0035% a side, as E05).
* Financing: the broker's FEE only (`zoo.financing.fee_and_differential` on today's swap quote),
  charged every day a position is held, long or short. The interest-rate differential is NOT
  applied from today's quote to past years; that is this project's standing rule, because the
  differential follows rates that were different then. C5 below checks the other extreme.
* Sharpe is annualised with the square root of 260 (weekday bars).

## Pass criteria, per pair, all five required

* **C1**: net Sharpe above 0.
* **C2**: net Sharpe above the **99th** percentile of 200 random-sign nulls (seeds 0 to 199) with
  the same stop and cost mechanics. 99th, not 95th, because five pairs are tested at once: at the
  95th, one of five would pass by luck about a quarter of the time.
* **C3**: net positive in at least 7 of the 11 calendar years 2015 to 2025.
* **C4**: net Sharpe above 0 with spread and commission doubled.
* **C5**: net Sharpe above 0 when TODAY'S full swap (fee and differential, long and short) is
  charged on every day held. This is what the account actually pays if it trades the pair now.

## What each outcome means

* A pair passes: it becomes a live candidate beside Ethereum. The engine may hold at most 2
  positions and 50% of equity in margin, so at most one pair trades beside ETH at a time; if
  more than one passes, the one with the highest net Sharpe goes first.
* No pair passes: the engine stays on Ethereum alone, and the answer to "why only one thing" is
  measured, not assumed: these are the only things it can afford, and the rule does not work on
  them.

## Counting

Five trials (one rule, five symbols). N was 300 at E07; N = 305 after E08. The deflated Sharpe
at N = 305 is reported for each pair and is not a pass criterion, as in E05 to E07.
