# Universe sweep, 2026-09-16

Both fitted models against all 24 instruments, six years of H1 bars each.

**Result: 48 pairs, 27 evaluable, 1 positive on both measures, 0 survive the gate.**

The databases are gitignored, so this file is the durable record of the run. Regenerate with `python -m scripts.sweep_universe --report`.

## The finding nobody was looking for

Across 27 evaluable pairs, **1 was positive on both development and holdout, where pure chance predicts about 7**. The models are systematically worse than coin flips, which is what trading costs do to a signal that has no edge.

## Results

| symbol | class | model | bars | dev OOF | holdout | folds |
|---|---|---|---|---|---|---|
| HK50 | index | kalman_level | 23,929 | -0.642 | 1.273 | 4/4 |
| ADAUSD | crypto | kalman_level | 25,516 | 0.668 | 1.030 | 4/4 |
| XTIUSD | energy | kalman_level | 35,417 | -0.158 | 0.982 | 4/4 |
| ETHUSD | crypto | kalman_level | 43,549 | -0.306 | 0.753 | 4/4 |
| XBRUSD | energy | kalman_level | 32,756 | -0.314 | 0.734 | 4/4 |
| AUDUSD | fx_major | kalman_level | 37,296 | -0.197 | 0.582 | 4/4 |
| GBPUSD | fx_major | kalman_level | 37,294 | -0.896 | 0.499 | 4/4 |
| USDCHF | fx_major | kalman_level | 37,293 | -1.017 | 0.198 | 4/4 |
| DE40 | index | kalman_level | 34,679 | -0.170 | 0.147 | 4/4 |
| XAUUSD | metal | ou_reversion | 35,434 | -0.352 | 0.000 | 2/4 |
| XAGUSD | metal | ou_reversion | 35,393 | -0.670 | 0.000 | 1/4 |
| XAUEUR | metal | ou_reversion | 35,435 | -0.430 | 0.000 | 1/4 |
| XAGUSD | metal | kalman_level | 35,393 | 0.323 | -0.136 | 4/4 |
| US500 | index | kalman_level | 35,366 | -0.564 | -0.145 | 4/4 |
| AUDJPY | fx_cross | kalman_level | 37,296 | -0.830 | -0.340 | 4/4 |
| AUS200 | index | kalman_level | 32,685 | 0.570 | -0.509 | 4/4 |
| EURUSD | fx_major | kalman_level | 37,293 | -0.182 | -0.516 | 4/4 |
| USDCAD | fx_major | kalman_level | 37,293 | -1.627 | -0.671 | 4/4 |
| EURAUD | fx_cross | kalman_level | 37,293 | -1.329 | -0.704 | 4/4 |
| GBPJPY | fx_cross | kalman_level | 37,293 | -2.230 | -0.832 | 4/4 |
| NZDUSD | fx_major | kalman_level | 37,290 | 0.660 | -0.853 | 4/4 |
| BTCUSD | crypto | kalman_level | 43,532 | -0.204 | -0.886 | 4/4 |
| XAUEUR | metal | kalman_level | 35,435 | -1.755 | -0.937 | 4/4 |
| XAUUSD | metal | kalman_level | 35,434 | -1.130 | -1.095 | 4/4 |
| EURGBP | fx_cross | kalman_level | 37,293 | -1.498 | -1.652 | 4/4 |
| USDJPY | fx_major | kalman_level | 37,293 | -1.543 | -2.030 | 4/4 |
| EURJPY | fx_cross | kalman_level | 37,293 | -2.303 | -2.307 | 4/4 |
| EURUSD | fx_major | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| GBPUSD | fx_major | ou_reversion | 37,294 | — | — | **NOT EVALUABLE** |
| USDJPY | fx_major | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| AUDUSD | fx_major | ou_reversion | 37,296 | — | — | **NOT EVALUABLE** |
| USDCAD | fx_major | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| USDCHF | fx_major | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| NZDUSD | fx_major | ou_reversion | 37,290 | — | — | **NOT EVALUABLE** |
| EURGBP | fx_cross | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| EURJPY | fx_cross | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| GBPJPY | fx_cross | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| AUDJPY | fx_cross | ou_reversion | 37,296 | — | — | **NOT EVALUABLE** |
| EURAUD | fx_cross | ou_reversion | 37,293 | — | — | **NOT EVALUABLE** |
| US500 | index | ou_reversion | 35,366 | — | — | **NOT EVALUABLE** |
| DE40 | index | ou_reversion | 34,679 | — | — | **NOT EVALUABLE** |
| HK50 | index | ou_reversion | 23,929 | — | — | **NOT EVALUABLE** |
| AUS200 | index | ou_reversion | 32,685 | — | — | **NOT EVALUABLE** |
| XTIUSD | energy | ou_reversion | 35,417 | — | — | **NOT EVALUABLE** |
| XBRUSD | energy | ou_reversion | 32,756 | — | — | **NOT EVALUABLE** |
| BTCUSD | crypto | ou_reversion | 43,532 | — | — | **NOT EVALUABLE** |
| ETHUSD | crypto | ou_reversion | 43,549 | — | — | **NOT EVALUABLE** |
| ADAUSD | crypto | ou_reversion | 25,516 | — | — | **NOT EVALUABLE** |

## The one candidate, and why it fails

ADAUSD kalman_level, dev 0.668, holdout 1.030. Four independent reasons:

1. **Deflated Sharpe 0.0000** against an honest N of 66. The bar is 0.95.
2. **Fitted q/R swings 10x across folds** (100, 178, 1000, 1000). On a synthetic series that genuinely contained the signal, the same model fitted an identical 0.001778 in all four folds. This is noise-chasing, not measurement.
3. **Two of four folds hit the grid ceiling**, which is a measurement error.
4. **No tick telemetry for ADAUSD**, so its cost is a 1.0-pip default (1.95 bps round trip), not a measurement. At small size cost is the dominant term.

## Ornstein-Uhlenbeck is not evaluable at H1

Its fitted half-life exceeds the test window on 21 of 24 instruments; the three that ran covered only 1-2 folds of 4. On EURUSD the estimate is 4,066 bars (169 days). That is a property of the sampling rate, not of any market.

## Caveats

- Only 8 of 24 instruments have measured spreads. The rest use conservative defaults, and those results carry a cost-model caveat.
- All 48 pairs are recorded against the cumulative trial count (18 to 66). A search that does not log its trials makes multiple testing worse, not better.

_Generated 2026-09-16 06:21._