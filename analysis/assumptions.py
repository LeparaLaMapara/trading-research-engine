"""Assumption Tester: check whether an idea's assumptions hold BEFORE backtesting.

The point is to fail fast. If a strategy assumes mean reversion, the target series had
better look mean-reverting on measured data, not on a hunch. These are diagnostics, not
decisions: they inform a human, they do not gate anything automatically.

Convention: pass a PRICE series to run_assumptions (it derives log returns internally).
The individual tests operate on whatever series you hand them, so call adf_test on the
series whose stationarity you actually care about.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import InterpolationWarning
from statsmodels.tsa.stattools import adfuller, kpss


def adf_test(series: pd.Series) -> dict:
    """Augmented Dickey-Fuller. Null = unit root (non-stationary).

    A low p-value rejects the unit root, so pvalue < 0.05 => stationary.
    """
    x = pd.Series(series).dropna().to_numpy()
    stat, pvalue = adfuller(x, autolag="AIC")[:2]
    return {"stat": float(stat), "pvalue": float(pvalue), "stationary": bool(pvalue < 0.05)}


def kpss_test(series: pd.Series) -> dict:
    """KPSS. Null = stationarity (opposite framing to ADF).

    A high p-value fails to reject stationarity, so pvalue > 0.05 => stationary_null holds.
    """
    x = pd.Series(series).dropna().to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InterpolationWarning)
        stat, pvalue = kpss(x, regression="c", nlags="auto")[:2]
    return {
        "stat": float(stat),
        "pvalue": float(pvalue),
        "stationary_null": bool(pvalue > 0.05),
    }


def hurst_exponent(series: pd.Series) -> float:
    """Estimate the Hurst exponent via variance of lagged differences.

    For a series x, Var(x[t+lag] - x[t]) scales like lag**(2H). Regressing log-variance
    on log-lag gives slope 2H. Interpretation: H < 0.5 mean-reverting, ~0.5 random walk,
    H > 0.5 trending/persistent.
    """
    x = pd.Series(series).dropna().to_numpy(dtype=float)
    n = x.size
    if n < 20:
        return float("nan")
    max_lag = max(2, min(n // 2, 100))
    lags = np.arange(2, max_lag)
    tau = []
    good = []
    for lag in lags:
        diff = x[lag:] - x[:-lag]
        var = np.var(diff)
        if var > 0:
            tau.append(var)
            good.append(lag)
    if len(good) < 2:
        return float("nan")
    log_lag = np.log(np.asarray(good, dtype=float))
    log_var = np.log(np.asarray(tau, dtype=float))
    slope = np.polyfit(log_lag, log_var, 1)[0]
    return float(slope / 2.0)


def autocorrelation(series: pd.Series, lags: int = 20) -> list[float]:
    """Sample autocorrelation for lags 1..lags (lag 0 is trivially 1 and omitted)."""
    s = pd.Series(series).dropna()
    n = s.size
    k = min(lags, max(0, n - 1))
    return [float(s.autocorr(lag=i)) for i in range(1, k + 1)]


def run_assumptions(series: pd.Series) -> dict:
    """Summarize all assumption tests on a PRICE series plus a plain-English verdict.

    Log returns drive stationarity/autocorrelation; the Hurst exponent runs on the price
    level (where mean reversion vs trending is most legible).
    """
    price = pd.Series(series).dropna()
    returns = np.log(price).diff().dropna()

    adf = adf_test(returns)
    kp = kpss_test(returns)
    hurst = hurst_exponent(price)
    acf = autocorrelation(returns, lags=20)

    if not np.isnan(hurst):
        if hurst < 0.45:
            verdict = "prices look mean-reverting (Hurst < 0.45)"
        elif hurst > 0.55:
            verdict = "prices look trending / persistent (Hurst > 0.55)"
        else:
            verdict = "prices look like a random walk (Hurst near 0.5)"
    else:
        verdict = "inconclusive (too little data to estimate Hurst)"

    return {
        "n": int(price.size),
        "adf": adf,
        "kpss": kp,
        "hurst": hurst,
        "autocorrelation": acf,
        "verdict": verdict,
    }
