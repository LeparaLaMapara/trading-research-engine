# Red team review: latency laboratory, Stage A

Adversarial review of the work committed on 2026-09-20 (`22bcf84`, `c3d4ed9`). Nothing in
`lab/`, `scripts/`, `backtest/`, `zoo/` or `telemetry/` was modified. Every number below was
produced by read only analysis or by mutating a throwaway copy of the repo in a scratch
directory. The broker was not contacted and the tick logger was not started.

Verdict summary:

| # | Claim | Verdict |
|---|---|---|
| 1 | ma_trend on EURUSD crosses zero between 18 and 20 hours of delay | BROKEN as a finding, UNPROVEN as a measurement |
| 2 | The fill is priced at the first H1 bar open at or after decision+delay | VERIFIED for the weekend case, BROKEN for negative delay and for the zero bucket |
| 3 | Delay zero equals the conventional backtest | BROKEN |
| 4 | Our clock is 86 ms behind true time | Direction VERIFIED, number BROKEN, implementation BROKEN |
| 5 | Costs are now conservative | BROKEN. The new cost code never executes |
| 6 | Every experiment row is reproducible; the tick hash survived the schema change | BROKEN |
| 7 | The test suite protects the lab | BROKEN. 18 of 22 mutations survive |

---

## Claim 5 first, because it invalidates claims 1 and 3

**"`measured_cost` now admits only two sided quotes with a positive spread, requires 200 of
them, and where a symbol's spread was observed in fewer than eight distinct hours of the week
it prices at the 75th percentile instead of the median."**

**Verdict: BROKEN. None of that code runs. Every cost number published on 2026-09-20 is a
hardcoded class constant, not a measurement.**

`backtest/run.py` closes the SQLite connection at line 85 and then reuses it at line 88.

```python
sp = pd.read_sql_query(..., c, params=(symbol.upper(),))
c.close()                                   # line 85
MIN_TICKS = 200
MIN_HOURS = 8
hours = pd.read_sql_query(
    "SELECT COUNT(DISTINCT hour_of_week) h FROM ticks WHERE symbol=? "
    "AND side='bid+ask' AND spread_pips > 0", c, params=(symbol.upper(),))   # line 88
```

The second call raises `ProgrammingError: Cannot operate on a closed database`, which the bare
`except Exception` at line 108 swallows, leaving `spread_pips` as `None`, which falls through
to the `_DEFAULT_SPREAD_BPS` fallback.

```
$ python -c "from backtest.run import measured_cost; ..."
  (no telemetry for EURUSD; assuming 2 bps of price = 2.20 pips at 1.10)
EURUSD spread_pips=2.2000 pip=0.0001 cost_bps=1.3500
  (no telemetry for XAUUSD; assuming 3 bps of price = 60.00 pips at 2000.00)
XAUUSD spread_pips=60.0000 pip=0.01 cost_bps=1.8500
  (no telemetry for USDJPY; assuming 2 bps of price = 2.80 pips at 140.00)
USDJPY spread_pips=2.8000 pip=0.01 cost_bps=1.3500
  (no telemetry for BTCUSD; assuming 15 bps of price = 9000.00 pips at 60000.00)
BTCUSD spread_pips=9000.0000 pip=0.01 cost_bps=7.8500
```

Those are exactly the four numbers in the "after" column of
`docs/results/frontier-cycle-2026-09-20.md` section 3: 1.35, 1.35, 1.85, 7.85. They are
`0.5 * bps * 1e-4 + 0.000035` for `fx_major=2.0`, `metal=3.0`, `crypto=15.0`. They are
arithmetic on constants. The line "measured costs were too kind, and fixing them made every
result worse" describes a change that replaced a measurement with a guess, and the guess
happens to be larger.

There is telemetry. EURUSD has 4,493 admissible two sided positive spread ticks, well past the
200 floor:

```
$ ... SELECT spread_pips FROM ticks WHERE symbol='EURUSD' AND side='bid+ask' AND spread_pips>0
admissible EURUSD ticks 4493
EXCEPTION on closed conn: ProgrammingError Cannot operate on a closed database.
```

### And on the merits: is p75 of a two hour sample conservative for the other 22 hours?

No. It is conservative for the quiet hours and badly unconservative for the one hour that
matters. XAUUSD has the most coverage in the database, 88,471 admissible ticks over 15 of 24
UTC hours:

```
-- XAUUSD: 88,471 admissible ticks, 15 distinct hour_of_week, 15 of 24 UTC hours observed
   p75 of the 14-15 UTC 'cheapest' window = 10.00 pips
   median of the hourly medians across all observed hours = 9.00 pips -> OVERSTATES by +11%
   observed hours where the true median EXCEEDS that p75: [2, 9, 21, 23]
        (worst 40.0 pips at 09:00 UTC = 4.0x the estimate)
   share of observed ticks quoted WIDER than the p75 estimate: 38.6%
   UTC hours never observed at all: [8, 10, 11, 12, 13, 17, 18, 19, 20]

-- USDJPY: p75 of cheap window 0.20 pips; 21:00 UTC median 6.2 pips = 31.0x the estimate
-- NZDUSD: p75 of cheap window 0.50 pips; 21:00 UTC median 16.4 pips = 32.8x the estimate
-- GBPUSD: p75 of cheap window 0.40 pips; 21:00 UTC median 6.1 pips = 15.2x the estimate
```

**The number: for XAUUSD the p75 of the cheap window overstates the typical observed hour by
11 percent and understates the 21:00 UTC rollover hour by a factor of 4. For USDJPY and NZDUSD
the same estimator is short by a factor of 31 and 33 at the rollover.** Spread is not smooth in
the hour of day; it is flat all day and then explodes at the daily rollover. A percentile of a
sample that excludes the rollover cannot be conservative, whichever percentile you pick.

The `MIN_HOURS = 8` gate is also not measuring what its name says. EURUSD clears it on a single
Wednesday:

```
            ticks  distinct_how
2026-08-06     20             1
2026-09-15    586             3
2026-09-16   3886            10
2026-09-20      1             1
```

Eight consecutive hours on one day satisfies "eight distinct hours of the week", so the very
symbols the audit worried about are routed to the median branch, not the p75 branch. Had the
connection bug not made the point moot, the gate would have been a no op for every major.

---

## Claim 1: the 18 to 20 hour crossing

**Verdict: BROKEN as a published finding, UNPROVEN as a measurement.**

### It replicates arithmetically

I reimplemented the replay from scratch against `data/market.db`, importing nothing from
`lab/` (`scratchpad/rt1.py`). At the cost the stored experiment actually used, 0.39 bps, I
reproduce the stored curve:

```
 delay    netret   sharpe    meannet  mediantrade  meantrade  ntr  nobs
    0h    0.0728   0.1648     0.468b      -62.31b     18.66b   39  1555
   12h    0.0620   0.1391     0.399b      -63.43b     15.90b   39  1555
   18h    0.0022   0.0052     0.014b      -58.71b      0.58b   39  1555
   19h   -0.0096  -0.0221    -0.062b      -52.39b     -2.47b   39  1555
   20h   -0.0080  -0.0179    -0.051b      -53.13b     -2.05b   39  1555
```

Stored row for 64800 s: `net_return 0.002127, sharpe 0.004921`. Mine: 0.0022 / 0.0052. The
machinery does what it says.

Note that 19 h was never tested by the bisection (it evaluated 18 h, 21 h, 20 h) and is
negative, so the true bracket at that cost is (18 h, 19 h), not (18 h, 20 h).

### It does not survive the cost correction published in the same document

The bracket experiment `exp_20260920T102143Z_530739` was created at 10:21 UTC with
`code_commit 76ff6e6+dirty` and `cost_model "measured spread+commission 0.39bps"`. The cost
change landed at `c3d4ed9`, 12:54 SAST, after it. Section 2 and section 3 of
`frontier-cycle-2026-09-20.md` are therefore not consistent with each other. At 1.35 bps, the
number section 3 declares current:

```
   16h    0.0191   0.0441
   18h   -0.0051  -0.0119      <- the published "still positive" bucket is now NEGATIVE
   20h   -0.0154  -0.0344
```

The crossing moves to (16 h, 18 h). **The headline bracket does not hold under the cost model
published three paragraphs later in the same file.**

### Metric sensitivity

Swapping Sharpe for mean net return is not an independent check. `sharpe = mean/sd * sqrt(ppy)`
and `net_return = n * mean`, so all three quantities share a sign at every delay by
construction:

```
 delay    sharpe   sum net   mean bar  MEDIAN bar  MEDIAN trade
    0h    0.1648    0.0728     0.468b     -1.505b      -62.31b
   12h    0.1391    0.0620     0.399b     -1.312b      -63.43b
   18h    0.0052    0.0022     0.014b      0.019b      -58.71b
   24h   -0.0627   -0.0277    -0.178b     -1.854b      -55.93b
```

Under a median criterion the finding disappears entirely. The median trade is negative at every
delay including zero, and the median bar is negative at seven of the nine delays including
zero. `crossing_bracket` would return `no_edge`, meaning there is no crossing to bracket. The
strategy makes money from a small number of large winners, and "the delay at which the mean
crosses zero" is a statement about the tail, not about a typical trade.

### The bootstrap

Stationary block bootstrap, block 20 bars, 4,000 replicates, the same resampled index applied
to every delay so the coupling between buckets is preserved (`scratchpad/rt2.py`):

```
### cost 0.39 bps (as the stored experiment ran)
  sharpe@ 0h  point +0.1648   95% CI [-0.513, +0.897]  P(sharpe>0)=0.70
  sharpe@12h  point +0.1391   95% CI [-0.534, +0.872]  P(sharpe>0)=0.69
  sharpe@18h  point +0.0052   95% CI [-0.695, +0.785]  P(sharpe>0)=0.54
  sharpe@20h  point -0.0179   95% CI [-0.697, +0.751]  P(sharpe>0)=0.52
  sharpe@24h  point -0.0627   95% CI [-0.761, +0.693]  P(sharpe>0)=0.47
  bootstrap crossing status mix: {'censored': 0.494, 'bracketed': 0.294, 'no_edge': 0.212}
  crossing-hour 95% CI [9.0 h, 48.0 h]  median 48.0 h  IQR [19.0, 48.0]
  share of replicates whose crossing lands INSIDE the published (18,20) h bracket: 0.020
```

**Confidence interval on the crossing point: [9 h, 48 h], which is the entire grid.** Half the
replicates never cross at all inside the grid, a fifth show no edge at any delay including
zero, and only 2.0 percent put the crossing inside the published two hour bracket. The
bracket is reproducible one time in fifty under resampling of the same data.

At 39 trades the Sharpe at zero delay is +0.165 with a 95 percent interval of [-0.51, +0.90].
The lab's own `bootstrap_metric_ci` exists and would have said this, but `scripts/edge_decay.py`
never calls it. Nothing in the pipeline puts an interval on a bucket before the bisection
spends compute narrowing the gap between two buckets that are statistically identical.

### The confound nobody controlled for

D1 bars are stamped 21:00 UTC. The decision instant is therefore always 21:00 UTC, and the fill
hour is a deterministic function of the delay: 0 h fills at 21:00, 2 h at 23:00, 12 h at 09:00,
18 h at 15:00. Measured EURUSD cost per unit turnover by UTC fill hour, from the same telemetry
database the cost model is supposed to read:

```
uh
0..7   0.40 bps
9      0.80 bps
14,15  0.40 bps
21     4.71 bps     <- the 21:00 rollover, where the 0h bucket fills
22,23  0.40 bps
```

Replacing the flat cost with the measured hour specific cost:

```
 delay  fill hour  flat 1.35bps  hour-correct   verdict
    0h       21:00        0.1481        0.1168
    2h       23:00        0.1534        0.1701
   16h       13:00        0.0441        0.0611
   18h       15:00       -0.0119        0.0051   sign FLIPS
   24h       21:00       -0.0794       -0.1107
```

Execution delay and time of day are perfectly confounded in this design, and a single flat cost
per symbol hides it. The curve is at least partly a curve of "which hour you trade in", not of
latency. The 18 h bucket, the one the whole bracket rests on, changes sign on this correction
alone.

---

## Claim 2: the fill is the first H1 bar open at or after decision+delay

**Verdict: VERIFIED for the weekend case you were worried about. BROKEN for negative delay, for
the zero bucket's price source, and for silent row loss.**

Adversarial harness: `scratchpad/rt3.py`.

**The weekend case is correct.** A Friday 21:00 UTC decision with a 12 h delay on a tape whose
Friday prices are 1.10 and Monday prices are 1.20:

```
=== E. WEEKEND GAP: Friday-night decision, 12h delay ===
  decided_ts    filled_ts  effective_delay_s  price
1789160400.0 1789333200.0           172800.0    1.2
filled at 2026-09-13 21:00:00 price 1.2 ->  CORRECT (Monday price)
effective delay reported: 48.0 h for a 12h request
```

`np.searchsorted(..., side="left")` cannot return an index whose timestamp is below the target,
so a fill in the past is structurally impossible for a positive delay. The effective delay is
reported honestly as 48 h.

**But the effective delay is then collapsed to a median before it is published.**
`decay_curve` stores `fills["effective_delay_s"].median()`. On the real EURUSD tape:

```
  req      n   median     mean      p90      max >1.5x req  dupe fills
   1h   1555      1.0      1.0      1.0      5.0     0.2%           0
  18h   1555     18.0     18.0     18.0     18.0     0.0%           0
  20h   1555     20.0     20.0     20.0     20.0     0.0%           0
  24h   1554     24.0     33.8     72.0     96.0    20.4%           0
  48h   1553     48.0     62.7     96.0    120.0    20.9%         315
```

The 24 h bucket is published as "24 h" while 20.4 percent of its fills are between 36 h and 96
h late. At 48 h, 315 of 1,553 decisions land on the same bar as their predecessor, so two
consecutive decisions get the identical price, one trade's return collapses to zero, and
turnover is charged twice. The buckets at and beyond 24 h are not delay buckets. Fortunately
the 18 h and 20 h buckets are clean, so this does not explain the bracket, but the coarse grid
that produced the original (12 h, 24 h) bracket was contaminated at its upper end.

**Negative delay is accepted and produces lookahead:**

```
=== A. NEGATIVE delay is accepted and fills IN THE PAST (lookahead) ===
 decided_ts  filled_ts  effective_delay_s  price
    18000.0     7200.0           -10800.0  102.0
VERDICT: LOOKAHEAD ACCEPTED
```

The guard is `if 0 < delay_s < step`, which is false for any negative number. A sign error in a
caller, or a future "negative delay means we acted early" experiment, walks straight into
trading in the past with no exception raised.

**A sub bar delay that is not sub bar is silently rounded:**

```
=== C. non-integer-hour delay is silently rounded UP, not refused ===
requested 5400s -> effective 7200.0 s (no error, no warning)
```

That is documented in the docstring, so it is a design choice rather than a defect, but nothing
warns at run time and the requested value is what is printed in the left hand column of the
report.

**Rows are dropped with no warning when the delay outruns the data:**

```
=== F. delay longer than the remaining data: rows SILENTLY DROPPED ===
  delay  1h -> 3/3 decisions survive (no warning emitted)
  delay  5h -> 2/3 decisions survive (no warning emitted)
  delay 20h -> 0/3 decisions survive (no warning emitted)
```

In the stored curve this shows up as `n_obs` 1555, 1554, 1553 across buckets. The buckets being
compared are not on the same sample. With a 30 fill floor, a bucket can quietly lose most of its
sample and still be reported as a point on the curve.

**A missing bar rolls forward and reports honestly** (requested 4 h, filled at 5 h, effective 5
h). **Duplicate timestamps** pick an arbitrary member of the tie. **Unsorted input** is sorted
internally.

**The zero bucket is not on the same price series as any other bucket.** At delay 0 the price
comes from `signals.decision_price` (the D1 close) and never touches the execution tape:

```
=== H. delay 0 vs delay>0 use DIFFERENT PRICE SOURCES ===
  delay 0 price = 999.0 (signals.decision_price, NOT the tape)
  delay 1h price = 104.0 (tape open)
```

On the real data the two series differ systematically:

```
D1 close(t-1)  vs  H1 open at the same stamp, in bps:
  mean -2.60  median -1.87  sd 7.88  p95 |diff| 11.51  max |diff| 127.58
```

A mean gap of 2.6 bps between two prices that should be the same instant, on the instrument
whose entire round trip cost is being modelled at 1.35 bps. This is the 21:00 rollover again.
It does not corrupt within bucket returns, which stay inside one series, but the zero bucket is
not the same experiment as the others and should not be plotted on the same axis without saying
so.

**`decision_price` is dropped, so the slippage diagnostic can never fire.**
`fills_for_delay` returns only six columns and `decision_price` is not one of them, so
`pnl_from_fills`'s `f.get("decision_price", NaN)` is always NaN and `decay_curve`'s
`delay_slippage_bps` is never computed. Every `delay_slippage_bps` value in `edge_decay` is
NULL. The comment calls it "the mechanism behind any decay seen"; it has never been measured.

---

## Claim 3: delay zero equals the conventional backtest

**Verdict: BROKEN.**

Holding positions, window, costs and annualisation identical, and comparing
`lab` delay 0 against `backtest.harness.run_backtest`:

```
harness (identical positions): sharpe +0.308000 net +0.13589704 trades 39
lab delay 0                  : sharpe +0.315521 net +0.13933345 trades 39
rows that differ: 2 -> [   0 1554]  diffs: [0.00266583 0.00077057]
net-sum difference: 0.003436401097006603
```

Two boundary defects:

* Row 0. The harness zeroes the first bar (`pct_change().fillna(0)`); the lab charges the real
  first bar return. The lab is arguably more correct here.
* Row 1554. `pnl_from_fills` does `price.pct_change().shift(-1)`, so the **final bar's return
  is silently discarded**. One whole bar of P&L, 7.7 bps on this run, vanishes from every
  bucket. At longer delays more rows go the same way.

And the difference that actually matters, on the numbers as they are published:

```
harness, SAME window       sharpe +0.3230  net sum +0.141221  trades 37  n 1555
harness, FULL D1 history   sharpe +0.2810  net sum +0.263062  trades 70  n 3116
lab delay 0 (fin=0)        sharpe +0.3155  net sum +0.139333  trades 39  n 1555
lab delay 0 as published   sharpe +0.1645
```

The published zero delay Sharpe is 0.16. The conventional backtest on the same window is 0.32.
The factor of two is financing: the lab charges `fee/365` per day on `|position|` and
`backtest/harness.py` charges none (0.0666 of the 0.0728 net return is financing drag). The
lab's treatment is the better one, but `scripts/edge_decay.py` docstring and the milestone
table both present the zero row as "the conventional assumption ... which is the thing being
tested", and it is not. It is the conventional assumption plus a financing model plus a
different price series plus a dropped final bar.

---

## Claim 4: our clock is 86 ms behind true time

**Verdict: direction VERIFIED, magnitude BROKEN, implementation BROKEN.**

### The packet parsing is correct

`struct.unpack("!12I", data[:48])` with words 8/9 as the server receive timestamp and 10/11 as
the server transmit timestamp matches RFC 5905. `offset = ((T2-T1) + (T3-T4))/2` and
`delay = (T4-T1) - (T3-T2)` are the standard formulas and the signs are right. `offset_ms` is
"add this to the local clock", and `corrected_latency_ms` adding it is arithmetically correct
even though the docstring says "subtracts it".

Local clock resolution is not the problem. On Python 3.13 this machine reports
`GetSystemTimePreciseAsFileTime()` at 1e-7 s.

### The number is not 86 ms and it is not stable

Five consecutive runs of `lab.clock.measure()` plus `consensus()`:

```
run 1: google +110.65 rtt 229.94 | pool +147.73 rtt 138.93 | cloudflare +161.03 rtt 156.87
       consensus offset +147.73 ms, uncertainty 94.66 ms
run 2: google  +88.69 rtt 186.85 | pool +117.29 rtt  75.86 | cloudflare +125.86 rtt  86.38
       consensus offset +117.29 ms, uncertainty 56.51 ms
run 3: consensus offset +116.26 ms, uncertainty 40.22 ms
run 4: google  +86.44 rtt 185.82 | ...  consensus offset +114.98 ms, uncertainty 55.29 ms
run 5: consensus offset +119.88 ms, uncertainty 42.25 ms
```

The consensus offset ranges 115 to 148 ms. The published 86 ms appears exactly once, as a
single `time.google.com` sample in run 4, and `consensus()` did not select it in any run
because Google's path from here has roughly twice the round trip of the other two.

Independent confirmation from a different tool and a different server:

```
> w32tm /stripchart /computer:time.windows.com /samples:5 /dataonly
13:53:35, +00.1113623s
13:53:37, +00.1024581s
13:53:40, +00.1234354s
13:53:42, +00.0991129s
13:53:44, +00.0932057s
> w32tm /query /status
Root Dispersion: 8.2127929s
Last Successful Sync Time: 9/20/2026 9:00:06 AM
Poll Interval: 10 (1024s)
```

So the clock genuinely is behind, by roughly 100 ms at 13:53, and it is drifting: the machine
last synced at 09:00 and the Windows root dispersion is 8.2 s. The direction of the correction
is right. The specific figure of 86 ms is an unlucky single sample, and because `clock_samples`
is **empty** (`SELECT * FROM clock_samples` returns zero rows) nothing about the published
figure or the claimed drift tracking is recoverable from the database. The commit message and
`frontier-cycle-2026-09-20.md` both state that `clock_samples` stores every sample. It stores
none.

### Is 86 ms an artefact of path asymmetry?

Partly, but not mainly. Pre resolving the IP so that DNS is outside the measured window, 15
samples per server:

```
  time.google.com     216.239.35.8   offset median  +99.49 min  +94.06 max +120.48 | delay median 199.46
  time.cloudflare.com 162.159.200.1  offset median +102.62 min  +94.53 max +107.59 | delay median  39.79
  time.nist.gov       132.163.97.6   offset median +111.79 min +101.74 max +313.22 | delay median 284.41
  pool.ntp.org        139.84.231.151 offset median  +98.25                          | delay median  39.38
```

Four independent servers with round trips spanning 39 ms to 284 ms all agree on roughly +95 to
+112 ms. If asymmetry dominated, servers with a 7x difference in path length would not agree to
within 15 ms. The offset is real. What is artefactual is the precision: the value moves 20 to
30 ms between runs, so quoting it to the nearest millisecond is not meaningful, and the honest
statement is "this machine is about 0.1 s behind, moving".

DNS resolution does sit inside `query()`'s t1 to t4 window (`socket.sendto` with a hostname
resolves inline), which inflates both the reported round trip and, by half the DNS time, the
offset. On a cold cache that is tens of milliseconds of pure bias. It is not the main effect
here, but it is a real defect.

### The implementation has a live failure mode that returns nonsense

`query()` validates nothing. No leap indicator check, no stratum 0 check, no mode check, no
"transmit timestamp is not zero" check. `pool.ntp.org`, which is in `DEFAULT_SERVERS`,
rate limits this host and answers with Kiss o' Death packets:

```
  sample  1: li=3 mode=4 stratum=0 refid=b'RATE' xmt_hi=0 rx_hi=0
             OFFSET -3998894162274.4 ms  <-- ACCEPTED BY lab/clock.py
  sample  5: ... same
  sample  9: ... same
  ...
5/20 replies were invalid per RFC 5905 and none are rejected by lab/clock.query().
```

An offset of minus four trillion milliseconds, about 126,000 years, is returned as a valid
measurement. And because a KoD packet is generated instantly it has the **shortest** round
trip, so `consensus()`, which picks `min(round_trip_ms)`, selects it preferentially:

```
consensus() picks min round_trip_ms -> a Kiss-o'-Death packet (tiny delay) WINS:
   consensus = (-3990000000000.0, 1995000000057.85)
```

This is reproducible today against a server the module ships with by default. Any latency
corrected with that offset becomes arbitrary. `corrected_latency_ms`'s guard rails do not
help: with an uncertainty of 2e12 ms everything reports "BELOW CLOCK UNCERTAINTY", which is at
least fail loud, but `record_clock` would have written the garbage to `clock_samples` first and
`clock_drift` would then report a fictional drift rate forever.

One further point on `consensus`: mixing `time.google.com`, which smears leap seconds, with
`time.cloudflare.com` and `pool.ntp.org`, which do not, means the "spread" term is measuring a
protocol difference as if it were clock uncertainty.

---

## Claim 6: reproducibility and hashing

**Verdict: BROKEN on both halves.**

### The tick content hash does NOT survive the schema change

`telemetry/store.py` carries an explicit promise:

> They are deliberately OUTSIDE TICK_COLS, which is the canonical hashed column set. Adding a
> column to the hash would change the content hash of the same underlying ticks, silently
> invalidating every snapshot digest recorded before today.

Testing both recorded snapshots by recomputing `content_hash` over the identical rows:

```
snapshot rows=    969 stored=5759bb24b175ba6c  recomputed=5759bb24b175ba6c  MATCH=True
snapshot rows= 361683 stored=eadf54de1bf9e081  recomputed=0e65cc2fa2dfedd7  MATCH=False
```

The 361,683 row snapshot taken this morning does not reproduce. The row set is exactly right
(361,683 rows, same count), so this is a serialization change, and the cause is provable from
the artefact the snapshot itself wrote:

```
parquet rows 361683 cols [... 'side', 'server_ts', 'recv_latency_ms']     <- 17 columns
recorded sha256                      : eadf54de1bf9e081e71ec9bbb5f320f9cd7feeef603e4e2768b1e306dccc1721
hash over TICK_COLS (15, today)      : 0e65cc2fa2dfedd7ebc1778f53bf00d0508d13817a17f96125b537728a94eeeb
hash over ALL_TICK_COLS (17)         : eadf54de1bf9e081e71ec9bbb5f320f9cd7feeef603e4e2768b1e306dccc1721
server_ts non-null in the snapshot: 25 of 361683
```

The digest recorded in the manifest is the hash over all 17 columns. Today's `content_hash`
hashes 15. The parquet file is also wrong: `snapshot()` writes `df[TICK_COLS]`, yet this file
has 17 columns, so it was written by an intermediate uncommitted state of the code in which
both the hash and the export used `ALL_TICK_COLS`. The file is named after a digest that today's
code will never produce for its contents. Two of 361,683 rows' worth of instrumentation, 25 non
null `server_ts` values, moved the canonical digest of the whole dataset. This is precisely the
failure the comment says was avoided, and the August snapshot survived only because it predates
the columns entirely.

### `data_hash` contains no data

`scripts/edge_decay.py` records `data_hash=episodes.data_hash({"n_sig":..., "n_h1":..., "last":
...})`. That is a hash of three summary numbers.

```
data_hash from the real data : 19c44b54272a46cd  stored: 19c44b54272a46cd  MATCH: True
data_hash after HALVING every price: 19c44b54272a46cd
```

Halving every price in the execution tape leaves the recorded `data_hash` unchanged. It cannot
detect a refetch, a revision, or the placeholder XRPUSD bars and synthetic crypto volumes that
the data quality audit found on the same day. The field named `data_hash` in the
reproducibility table verifies row counts and a timestamp, nothing else.

### Can the most recent `edge_decay` experiment be regenerated from its row alone?

Approximately, not exactly, and only by guessing.

```
stored config_json keys: ['delays_s', 'params']
stored cost_model      : measured spread+commission 0.39bps; financing 1.11%/yr
stored code_commit     : 76ff6e6+dirty
stored seeds           : none (deterministic)
```

Missing from the row entirely: `cost_per_turnover` at full precision, `financing_per_day` at
full precision, `exec_period`, `bars_per_year`, `SAFETY_FACTOR`, the number of bisection
rounds, and the crossing metric. The cost is recoverable only from a free text string rounded
to two decimals. Reconstructing from that:

```
 requested_delay_s  net_return_stored  net_return_redone    d_net
              0.00           0.072648           0.072764 0.000116
          43200.00           0.061893           0.062009 0.000116
          64800.00           0.002127           0.002244 0.000116
          72000.00          -0.008115          -0.007999 0.000116
max |net diff| : 0.0001161168504385246
bracket regenerated: {'status': 'bracketed', 'lo': 64800.0, 'hi': 72000.0}
```

The bracket regenerates, but the 18 h bucket's entire margin above zero is 0.00213 and the
reproduction error from cost rounding alone is 0.000116. The published finding sits 18 rounding
errors above zero and one cost model change below it.

`code_commit` is `+dirty` for 14 of the 15 rows in `experiments`, so the code that produced
them is not in git and cannot be checked out. By the module's own standard, "a result that
cannot be re-run from its row is not a result", none of the 15 rows qualifies.

### `latency_events` double counts

```
rows: 3931  distinct values: 1965
value multiplicity: 2 -> 1960 values, 4 -> 2 values, 1 -> 3 values
telemetry.latency real sample count: 2172
```

The probe series was imported twice, 1,967 plus 1,964, which is why the architecture document
says 1,964 samples and the milestone document says 1,967 for the same measurement. Anything
reading `percentiles("broker_round_trip")` sees 3,931 observations where 2,172 exist.

`market_data_receive` has three rows, all with `instrument = NULL`. The milestone document
attributes them to BTCUSD, ETHUSD and ADAUSD; that attribution is not in the database, and
"market data latency" as a published figure rests on three observations corrected by a clock
offset that was never stored.

### `MEASURED_ORDER_PATH_MS` is not an order path

```
     probe     n          mn        mean           mx
0  version  2172  368.602991  945.054364  4940.559387
```

Every sample is a `ProtoOAVersionReq`. `feasible_from_here` compares a strategy's survival
threshold against it as though it were the order round trip, and the report line calls it
"measured order path". It is a version handshake, which does not traverse the matching engine,
does not carry risk checks, and is not what an order costs. The conclusion "feasible by a
factor of about 11,000" is robust to this, but the label is false and it will not be robust
when the threshold is seconds instead of hours.

---

## Claim 7: the test suite

**Verdict: BROKEN. 18 of 22 mutations survive the entire suite.**

Method: the repository was copied to a scratch sandbox, one line was mutated at a time, and
`tests/test_lab.py` was run against the mutant (`scratchpad/mutate2.py`). Nothing in the real
tree was touched.

```
=== 18/22 mutations SURVIVE the entire tests/test_lab.py ===
  * M1  replay: searchsorted side 'left' -> 'right' (off-by-one at a bar boundary)
  * M2  replay: fill at the bar's CLOSE instead of its OPEN
  * M4  replay: drop financing entirely
  * M5  replay: charge cost on |position| (time) instead of on turnover
  * M6  replay: effective_delay_s always reports the REQUESTED delay
  * M7b replay: allow NEGATIVE delay (fill before the decision)
  * M8  decay: crossing uses >= 0 instead of > 0
  * M9  decay: regime boundaries become strict (<= -> <)
  * M10 decay: bucket minimum 30 fills -> 1 fill
  * M11 decay: sharpe annualised with the WRONG periods (bars_per_year -> 1)
  * M12 decay: bisection midpoint biased to the optimistic end
  * M13 decay: ev_per_trade reports the MAX trade instead of the mean
  * M14 decay: SAFETY_FACTOR 0.25 -> 1.0 (operate exactly at the measured edge)
  * M16 clock: NTP offset sign flipped
  * M17 clock: consensus picks the LONGEST round trip, not the shortest
  * M18 clock: uncertainty is the FULL round trip, not half
  * M19 clock: read the REFERENCE timestamp as the server receive time (wrong RFC word)
  * M20 clock: delay formula drops the server's processing time
```

Only four mutations were killed: fill one bar early, accept a sub bar delay, take the operating
target from the optimistic end, and flip the sign in `corrected_latency_ms`.

Named test and named surviving mutation, worst first:

1. **`_tape()` helper, tests/test_lab.py:14-18.** `pd.DataFrame({"ts_utc": ..., "open": px,
   "close": px})` gives every bar an open equal to its close. **M2**, pricing the fill at the
   bar's close instead of its open, which is a full hour of lookahead on real data, is
   invisible to every test in the file because the fixture makes the two columns identical.
   This is the single most dangerous gap: the module's central promise is "the open of the
   first hourly bar at or after the delayed moment", and the fixture cannot tell an open from a
   close.

2. **`test_costs_are_charged_on_turnover_not_on_time`, line 64.** The name states exactly the
   property. The fixture sets `position = [1, -1, 1, -1, ...]`, so `|position|` is 1 everywhere
   and `|Δposition|` is 2 everywhere; the two are proportional, so **M5**, charging cost on
   `|position|` instead of on turnover, still satisfies `dear < free` and passes. The test
   proves only that a larger cost constant reduces P&L.

3. **`test_threshold_and_safety_margin`, line 92.** `assert target == 4 * HOUR *
   D.SAFETY_FACTOR` multiplies by the very constant it is meant to pin. **M14**, setting
   `SAFETY_FACTOR = 1.0` so the engine recommends operating exactly at the measured survival
   threshold, passes unchanged. The assertion is a tautology.

4. **`test_the_fill_is_never_in_the_past_and_the_effective_delay_is_reported`, line 43.** It
   asserts `filled_ts >= decided_ts + 2h`, which is a one sided bound. **M1**, changing
   `side="left"` to `side="right"` so that a delay landing exactly on a bar start skips to the
   next bar, satisfies the bound and passes. The "at or after" half of the contract, which is
   the whole point of the boundary case, is untested.

5. **`test_refinement_narrows_the_bracket_and_stops_at_the_data_resolution`, line 140.** It
   **skips on this machine**: the synthetic tape produces no crossing, so `pytest.skip` fires.
   The suite reports `..............s..`. `refine_bracket` is therefore untested in practice,
   and **M12**, biasing the bisection midpoint toward the optimistic end of the bracket, is
   never exercised. The bisection is what produced the 18 to 20 hour headline.

6. **No test calls `decay_curve` or `bucket_metrics` and asserts a number.** Every Sharpe
   assertion is against a hand built DataFrame. **M11**, annualising Sharpe with 1 instead of
   `bars_per_year`, and **M13**, reporting the maximum trade as `ev_per_trade`, both pass.

7. **No test ever passes `financing_per_day != 0`.** **M4**, deleting financing entirely,
   passes, although financing is 92 percent of the published net return at zero delay
   (0.0666 of 0.0728).

8. **`test_a_crossing_is_reported_as_an_interval_not_a_point`, line 118**, uses Sharpes of
   0.2, 0.1, -0.1, none of them zero, so **M8**, changing `> 0` to `>= 0` so that a flat zero
   curve is reported as an edge, passes. **`test_regimes_come_from_seconds_not_from_names`,
   line 112**, never tests a boundary value, so **M9**, `<=` to `<`, passes.

9. **`lab/clock.py` has exactly one test**, `test_clock_correction_refuses_to_claim_precision_
   it_does_not_have`, and it tests only the pure arithmetic of `corrected_latency_ms`.
   `query`, `measure`, `consensus` and `ClockSample.uncertainty_ms` have no test at all, which
   is why **M16 through M20**, including flipping the NTP offset sign, reading the wrong RFC
   packet word, and selecting the worst server instead of the best, all pass. That is the code
   that produced the 86 ms figure.

---

## Appendix: files used

* `scratchpad/rt1.py` independent replay, imports nothing from `lab/`
* `scratchpad/rt2.py` block bootstrap of the crossing point
* `scratchpad/rt3.py` adversarial inputs to `fills_for_delay`
* `scratchpad/mutate2.py` mutation harness against a sandbox copy of the repo

No broker tool was run. No file outside `docs/redteam/` was created or modified.
