"""Walk-forward evaluation and multiple-testing correction — the guard against the single
most common way these systems die: a pretty in-sample backtest that loses live.

Two ideas, both from the spec (§6, §9):

1. Walk-forward. Evaluate the strategy on sequential out-of-sample windows plus a holdout
   slice touched exactly once. A strategy whose edge only shows in one window is fragile.
   (These strategies have fixed, non-fitted parameters, so this measures STABILITY across
   time rather than refitting; when strategies gain fittable params, the same split becomes
   true train/test.)

2. Deflated Sharpe (Bailey & Lopez de Prado). If you try N strategies, the best one looks
   good by luck alone. The Probabilistic Sharpe Ratio asks: given skew, kurtosis and sample
   size, what is the probability the true Sharpe exceeds a threshold? The Deflated Sharpe
   sets that threshold to the expected MAXIMUM Sharpe from N trials — so a number that would
   be impressive once becomes unremarkable after 500 tries.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from backtest.harness import CostModel, run_backtest
from backtest.metrics import BARS_PER_YEAR
from strategy.base import Strategy

EULER_GAMMA = 0.5772156649015329


def per_obs_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    sd = r.std(ddof=0)
    return float(r.mean() / sd) if sd > 0 and len(r) else 0.0


def probabilistic_sharpe_ratio(returns: pd.Series, sr_benchmark: float = 0.0) -> float:
    """P(true per-observation Sharpe > sr_benchmark), adjusting for skew/kurtosis and n."""
    r = returns.dropna()
    n = len(r)
    if n < 3:
        return 0.0
    sr = per_obs_sharpe(r)
    g3 = float(skew(r))
    g4 = float(kurtosis(r, fisher=False))   # normal == 3
    denom = np.sqrt(1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr ** 2)
    if denom <= 0:
        return 0.0
    return float(norm.cdf((sr - sr_benchmark) * np.sqrt(n - 1) / denom))


def expected_max_sharpe(sharpe_std_across_trials: float, n_trials: int) -> float:
    """Expected maximum per-observation Sharpe from N independent zero-skill trials."""
    if n_trials < 2 or sharpe_std_across_trials <= 0:
        return 0.0
    a = norm.ppf(1.0 - 1.0 / n_trials)
    b = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(sharpe_std_across_trials * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b))


def deflated_sharpe_ratio(returns: pd.Series, n_trials: int,
                          sharpe_std_across_trials: float) -> float:
    """PSR evaluated at the expected-max-Sharpe threshold. > 0.95 is the usual bar."""
    sr0 = expected_max_sharpe(sharpe_std_across_trials, n_trials)
    return probabilistic_sharpe_ratio(returns, sr_benchmark=sr0)


def walk_forward(bars: pd.DataFrame, strategy: Strategy, costs: CostModel, period: str,
                 n_splits: int = 5, holdout_frac: float = 0.2) -> dict:
    bars = bars.sort_values("ts_utc").reset_index(drop=True)
    ppy = BARS_PER_YEAR.get(period.upper(), 6240)
    n = len(bars)
    holdout_start = int(n * (1.0 - holdout_frac))
    dev, holdout = bars.iloc[:holdout_start], bars.iloc[holdout_start:]

    split_summaries = []
    bounds = np.linspace(0, len(dev), n_splits + 1, dtype=int)
    for i in range(n_splits):
        chunk = dev.iloc[bounds[i]:bounds[i + 1]].reset_index(drop=True)
        if len(chunk) < 30:
            continue
        split_summaries.append(run_backtest(chunk, strategy, costs, ppy).summary)

    full = run_backtest(dev.reset_index(drop=True), strategy, costs, ppy)
    holdout_summary = (run_backtest(holdout.reset_index(drop=True), strategy, costs, ppy).summary
                       if len(holdout) >= 30 else None)

    sharpes = [s["sharpe"] for s in split_summaries]
    return {
        "n_bars": n,
        "dev_summary": full.summary,
        "dev_net_returns": full.net_returns,          # for deflated-Sharpe at the portfolio level
        "split_sharpes": sharpes,
        "split_sharpe_mean": round(float(np.mean(sharpes)), 3) if sharpes else 0.0,
        "split_sharpe_std": round(float(np.std(sharpes)), 3) if sharpes else 0.0,
        "split_sharpe_min": round(float(np.min(sharpes)), 3) if sharpes else 0.0,
        "holdout_summary": holdout_summary,           # touched once
    }
