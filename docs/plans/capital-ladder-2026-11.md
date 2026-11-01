# The capital ladder: what real money follows a scoreboard pass

**Status: written 1 November 2026 for the owner's signature. Not in force until signed.**
It changes nothing on its own. No code sends an order for a scoreboard player today, and the
signed live limits in `risk/limits.py` (6% risk per trade, 2 positions, 40% drawdown halt,
$20 floor) stay exactly as they are on every rung.

## Why a ladder

A pass on the scoreboard (E16 or E17) shows skill on paper at the live spread. It does not show
that real orders fill at those prices. Each rung buys one more piece of evidence with the least
money that can buy it, and every rung has a written way back down.

## The rungs

**Rung 0: paper (now).** Every player is locked and scored each hour. No money. Checked by
`python -m forecast.judge`.

**Rung 1: smallest real trades.** Opens only when `forecast.judge` shows PASS for a player
(the pre-registered rule: 4 weeks, enough hours, skill and paper profit both proven).
* Only that player, only the instrument group it passed on (for the news reader: currency pairs).
* The smallest size the broker allows (0.01 lot), one position at a time, each trade closed at
  the next hour like the paper trade, with a stop at 3 times the hourly volatility.
* Every trade is also paper-traded, so real and paper results sit side by side.
* Lasts 4 weeks or 200 real trades, whichever is later.
* **Up to rung 2** when real net profit per trade is above 0 and real fills are no worse than
  paper by more than half the average spread.
* **Back to rung 0** (the player is retired) when the always-valid test says real net per
  trade is below 0 at 5%, or real fills are worse than paper by more than the average spread.

**Rung 2: full size within the signed limits, on the account's own money.** Trade size grows
to what the 6% risk per trade and 2-position limits allow on the balance at the time (about
$79 today). Nothing is added to the account. The same back-down rule as rung 1, checked every
day.

**Rung 3: owner adds money.** Only after 3 months on rung 2 with real net profit above 0 at 5%
(always-valid test). Every top-up is the owner's own decision, made each time, and raising the
ceiling (now R2,000) needs a newly signed grant. The ladder never asks for money by itself.

## Always, on every rung

* The $20 floor and the 40% drawdown halt latch everything off until the owner clears them.
* A rung is never skipped. A retired player can only come back as a new pre-registered version,
  starting again at rung 0.
* The order path for rung 1 is built and tested on demo only after a player passes, and the
  owner sees it before it touches the live account.

## Signature

Owner: ____________________   Date: ____________

(In a session, "I sign the capital ladder" is enough; it will be recorded here with the date.)
