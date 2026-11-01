# E17 pre-registration: the news reader (a fifth player on the forward scoreboard)

**Status: registered 1 November 2026, committed and pushed before the reader code exists.**
Programme P2, seventh slot. Owner on 2026-11-01: "implement everything", after agreeing the AI
news reader runs on this PC with a local open model (`NEWS_LLM=local`, Qwen 3.5 9B through
Ollama, `forecast/llm.py`), never sending broker or account data anywhere.

## The question

When a central bank or a statistics office publishes something, can a small local language
model, reading only what was published, tell which way the affected currencies move over the
following hours, by more than the spread?

## Sources (fixed here; official feeds only, free, no login)

| key | publisher | currency |
|---|---|---|
| fed | US Federal Reserve, all press releases | USD |
| bls_emp | US Bureau of Labor Statistics, jobs report | USD |
| bls_cpi | US Bureau of Labor Statistics, inflation report | USD |
| bea | US Bureau of Economic Analysis releases | USD |
| ecb | European Central Bank press | EUR |
| boe | Bank of England news | GBP |
| boj | Bank of Japan what's new | JPY |
| snb | Swiss National Bank press releases | CHF |
| boc | Bank of Canada press releases | CAD |
| rba | Reserve Bank of Australia media releases | AUD |
| rbnz | Reserve Bank of New Zealand news | NZD |

The exact URLs are in `news/feeds.py`. A source that stops working is shown, not replaced.

## What runs (this PC only)

1. **Read, every 5 minutes** (inside the standalone scoreboard loop, never in the last 5 minutes
   of an hour so it cannot delay the hourly cycle): fetch every feed; each item not seen before
   gets `fetched_utc` (this PC's clock). On the very first run every item already in the feeds is
   marked `backlog` and never scored. Items published more than 24 hours before they are fetched
   are skipped.
2. **Score each new item once** through the doorway: the title, the feed summary and up to 4000
   characters of the page text go to the local model with a fixed prompt (in `news/reader.py`)
   asking, for each of USD EUR GBP JPY CHF CAD AUD NZD, a number from -1 (this news should weaken
   it) to +1 (strengthen it), 0 for no effect, plus one confidence from 0 to 1. Temperature 0.
   Every request and answer is kept (`data/llm/replay.jsonl`) so any score can be re-checked.
   The item, its scores and `scored_utc` go to `data/news/items.jsonl`.
3. **Predict, inside the hourly cycle.** For hour H, only items with `scored_utc` before H itself
   count (the measured move starts at H's opening price, so nothing read after H is used). Each
   currency's signal is the sum over items fetched in the 24 hours before H of
   `score x confidence x exp(-age_hours / 6)`.
4. **Map to instruments.** For a symbol whose first three and last three letters are currency
   codes: signal(first) minus signal(last); a code outside the eight above (gold, silver,
   platinum, palladium, NOK, SEK, ZAR, MXN, PLN, SGD) counts as 0. So XAUUSD gets minus the USD
   signal and USDZAR gets the USD signal. Crypto, stock indices and oil get no view.
5. **Size.** Predicted move = 0.25 x signal, in units of the instrument's 24-hour volatility
   (one confident, maximal item is a quarter of a typical hourly move). An instrument with
   signal 0 gets no prediction. If fewer than one instrument has a view, the player writes
   nothing that hour ("no view").
6. **Lock and score exactly like the E16 players**: the same ledger, hash chain, published
   fingerprints, resolution at the next snapshot, the same paper trade rule (trade when the
   predicted move is bigger than the live spread, filled at the real bid and ask). Each line
   also lists the ids of the news items behind it. The player is named `news`, version `n1`.

## Pass criteria

Checked at any time after **4 weeks and 100 hours with a view** (always-valid tests):

1. mSPRT p-value for mean hourly rank correlation (IC) above 0, over hours with at least 5
   resolved predictions, below 0.05.
2. Paper book mean hourly net P&L above 0 with mSPRT p-value below 0.05.

Both hold: the first rung of the capital ladder, which the owner signs. One without the other is
not a pass. After 12 weeks without a pass, `n1` is recorded FAIL.

## Trials counted

1. This is its own experiment, judged at 0.05; it is not pooled into the E16 Holm correction.
A later prompt, model or source list is a new version and a new counted trial.

## What would make me wrong

* Markets price an official statement within seconds to minutes; by the next hour's opening
  price most of the move has happened. The most likely honest outcome is no skill. The test is
  whether any drift after the release remains.
* Most feed items (speeches, appointments, research papers) carry no news; the model must say 0
  for them. If it reads direction into noise the IC will show it.
* A 9B model can misread a statement. The kept requests let every score be checked by hand.
* The PC must be on. Hours it is off are missed, never backfilled; items fetched late are
  dated by when they were fetched, not when they were published.

## Correction, 1 November 2026, before any item was scored

A clerical slip: the kept requests and answers live in `data/forecast/llm-replay.jsonl` (the
doorway's store), not `data/llm/replay.jsonl`. Nothing else changes. The first real pass marked
287 items already in the feeds as backlog; the RBA feed currently lists almost nothing.
