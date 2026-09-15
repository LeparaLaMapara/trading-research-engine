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

from backtest import metrics
from backtest.harness import CostModel, run_backtest
from backtest.metrics import BARS_PER_YEAR
from strategy.base import Strategy

# A fold must hold a position for at least this many bars to count as evaluated. Below it the
# model was not tested, and a Sharpe computed from it is noise wearing a number's clothes.
MIN_ACTIVE_BARS = 30

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


def walk_forward_refit(bars: pd.DataFrame, make_strategy, costs: CostModel, period: str,
                       n_splits: int = 5, holdout_frac: float = 0.2,
                       min_train: int = 250) -> dict:
    """Anchored walk-forward that REFITS before every test window.

    `make_strategy` is a zero-argument factory returning a fresh, unfitted strategy. A fresh
    instance per fold matters: a reused object can carry state from a later period backwards,
    which is lookahead that no amount of careful indexing will catch.

    The procedure:

        fold i:  fit on every bar BEFORE fold i   ->  predict on fold i only
        ...
        holdout: fit on all development data      ->  predict on the holdout, once

    The reported development performance is the concatenation of out-of-fold predictions, so
    no bar is ever scored by a model that was fitted on it. That is the whole point.

    `walk_forward` (no refit) remains correct for strategies with fixed human-chosen
    parameters. Using it on a fitted strategy would score the model on its own training data
    and report a number that means nothing.
    """
    bars = bars.sort_values("ts_utc").reset_index(drop=True)
    ppy = BARS_PER_YEAR.get(period.upper(), 6240)
    n = len(bars)
    holdout_start = int(n * (1.0 - holdout_frac))
    dev, holdout = bars.iloc[:holdout_start], bars.iloc[holdout_start:]

    bounds = np.linspace(0, len(dev), n_splits + 1, dtype=int)
    oof_returns: list[pd.Series] = []
    oof_trades: list = []
    fold_active: list[int] = []
    split_summaries, fold_params = [], []

    for i in range(n_splits):
        lo, hi = bounds[i], bounds[i + 1]
        train = dev.iloc[:lo]                      # anchored: everything strictly before
        test = dev.iloc[lo:hi].reset_index(drop=True)
        if len(train) < min_train or len(test) < 30:
            continue                               # too little history to fit honestly
        strat = make_strategy()
        if hasattr(strat, "fit"):
            strat.fit(train.reset_index(drop=True))
            fold_params.append(getattr(strat, "fitted_params", None))
        res = run_backtest(test, strat, costs, ppy)
        # A fitted model can ask for a lookback longer than the window it is being tested on.
        # It then produces almost no positions, and the backtest happily reports a Sharpe of
        # 0.0 as if that were a finding. It is not a finding, it is a failure to evaluate.
        active = int((res.positions != 0).sum())
        fold_active.append(active)
        if active < MIN_ACTIVE_BARS:
            continue
        split_summaries.append(res.summary)
        oof_returns.append(res.net_returns)
        oof_trades.extend(res.trade_pnls)

    if not oof_returns:
        # NOT EVALUABLE, which is different from "failed". The caller must not treat this as
        # a score of zero: nothing was measured, so nothing is known.
        return {"n_bars": n, "dev_summary": None, "dev_net_returns": pd.Series(dtype=float),
                "split_sharpes": [], "split_sharpe_mean": 0.0, "split_sharpe_std": 0.0,
                "split_sharpe_min": 0.0, "holdout_summary": None,
                "fold_params": fold_params, "fold_active_bars": fold_active,
                "evaluable": False,
                "why_not": ("the fitted lookback needs more history than each test window "
                            "provides, so the model was never actually exercised"),
                "refit": True}

    dev_returns = pd.concat(oof_returns, ignore_index=True)

    holdout_summary = None
    if len(holdout) >= 30 and len(dev) >= min_train:
        final = make_strategy()
        if hasattr(final, "fit"):
            final.fit(dev.reset_index(drop=True))
        holdout_summary = run_backtest(holdout.reset_index(drop=True), final, costs,
                                       ppy).summary

    sharpes = [s["sharpe"] for s in split_summaries]
    return {
        "n_bars": n,
        # Summarised from the CONCATENATED OUT-OF-FOLD returns. Every bar in this series was
        # scored by a model that had never seen it, which is the only number on this rung
        # that means anything.
        "dev_summary": metrics.summarize(dev_returns, oof_trades, ppy),
        "dev_net_returns": dev_returns,
        "split_sharpes": sharpes,
        "split_sharpe_mean": round(float(np.mean(sharpes)), 3) if sharpes else 0.0,
        "split_sharpe_std": round(float(np.std(sharpes)), 3) if sharpes else 0.0,
        "split_sharpe_min": round(float(np.min(sharpes)), 3) if sharpes else 0.0,
        "holdout_summary": holdout_summary,
        "fold_params": fold_params,      # how stable the estimates are across time
        "fold_active_bars": fold_active,  # bars where a position was actually held
        "evaluable": True,
        # How much of the development period actually exercised the model. Partial coverage
        # is a warning: a model that only traded in the early folds because its later fits
        # asked for windows wider than the fold is being scored on a fraction of the period,
        # and the Sharpe is not describing what it appears to describe.
        "folds_evaluated": len(split_summaries),
        "folds_attempted": len(fold_active),
        "refit": True,
    }
