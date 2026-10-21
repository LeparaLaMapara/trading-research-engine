"""Statistics for deciding fast without fooling ourselves. Pure functions, no I/O.

* PBO by combinatorially symmetric cross-validation (Bailey, Borwein, Lopez de Prado and Zhu,
  "The Probability of Backtest Overfitting", J. Computational Finance 2017; SSRN 2326253,
  2014). Given T x N returns of N configurations, how often does the configuration that looks
  best in-sample land in the bottom half out of sample?
* The Harvey, Liu and Zhu bar ("... and the Cross-Section of Expected Returns", Review of
  Financial Studies 2016): t > 3 for a NEW factor family; a replication of a published family
  keeps the classical t > 2.
* Always-valid p-values from the normal-mixture sequential probability ratio test (mSPRT;
  Robbins 1970; Johari, Pekelis and Walsh, "Always Valid Inference", Operations Research
  2022). The p-value may be checked after every forward trade without inflating the error
  rate, so a forward test can stop the moment the evidence is decisive.
* Thompson sampling (Normal-Normal) to share a few demo slots between many candidates.
* Probability of ruin by simulation at the owner's signed limits.
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np

T_BAR_NEW_FAMILY = 3.0
T_BAR_PUBLISHED = 2.0


def t_bar(new_family: bool) -> float:
    return T_BAR_NEW_FAMILY if new_family else T_BAR_PUBLISHED


def t_stat(r) -> float:
    a = np.asarray(r, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * math.sqrt(len(a)))


def annual_sharpe(r, bars_per_year: float) -> float:
    a = np.asarray(r, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * math.sqrt(bars_per_year))


def sharpe_upper_bound(r, bars_per_year: float, z: float = 1.645) -> float:
    """One-sided upper confidence bound of the ANNUAL Sharpe (Lo 2002 standard error)."""
    a = np.asarray(r, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3 or a.std(ddof=1) == 0:
        return float("inf")
    sr = a.mean() / a.std(ddof=1)
    se = math.sqrt((1.0 + 0.5 * sr * sr) / len(a))
    return float((sr + z * se) * math.sqrt(bars_per_year))


# --------------------------------------------------------------------------- PBO (CSCV)
def pbo_cscv(returns: np.ndarray, n_blocks: int = 16, max_splits: int | None = None,
             seed: int = 0) -> dict:
    """Probability of backtest overfitting.

    returns: T x N matrix, one column per configuration (NaN allowed, treated as 0 = flat).
    The T rows are cut into n_blocks equal blocks; every half of the blocks is in-sample once,
    its complement out-of-sample. For each split the best in-sample configuration (by Sharpe)
    gets its relative OOS rank w in (0, 1); logit = ln(w / (1 - w)). PBO = share of logits
    <= 0, i.e. the in-sample winner was at or below the OOS median.
    """
    M = np.nan_to_num(np.asarray(returns, dtype=float))
    T, N = M.shape
    if N < 2 or T < 2 * n_blocks:
        return {"pbo": None, "splits": 0, "configs": N, "why": "too few configurations or rows"}
    edges = np.linspace(0, T, n_blocks + 1).astype(int)
    s1 = np.stack([M[edges[i]:edges[i + 1]].sum(0) for i in range(n_blocks)])
    s2 = np.stack([(M[edges[i]:edges[i + 1]] ** 2).sum(0) for i in range(n_blocks)])
    cnt = np.diff(edges).astype(float)
    combos = list(combinations(range(n_blocks), n_blocks // 2))
    if max_splits and len(combos) > max_splits:
        rng = np.random.default_rng(seed)
        combos = [combos[i] for i in rng.choice(len(combos), max_splits, replace=False)]
    allb = np.arange(n_blocks)

    def sharpe(idx):
        n = cnt[list(idx)].sum()
        m = s1[list(idx)].sum(0) / n
        v = s2[list(idx)].sum(0) / n - m * m
        return np.where(v > 0, m / np.sqrt(np.maximum(v, 1e-30)), 0.0)

    logits = []
    for c in combos:
        oos = np.setdiff1d(allb, c)
        is_sr, oos_sr = sharpe(c), sharpe(oos)
        best = int(np.argmax(is_sr))
        # relative rank of the IS winner among OOS Sharpes, 1 = best
        rank = (oos_sr < oos_sr[best]).sum() + 0.5 * ((oos_sr == oos_sr[best]).sum() - 1) + 1
        w = rank / (N + 1.0)
        logits.append(math.log(w / (1.0 - w)))
    lg = np.array(logits)
    return {"pbo": float((lg <= 0).mean()), "splits": len(lg), "configs": N,
            "median_logit": float(np.median(lg))}


# --------------------------------------------------------------------------- mSPRT
def msprt_p(x, mu0: float = 0.0, tau: float | None = None, sigma: float | None = None) -> float:
    """Always-valid p-value for H0: mean == mu0, after observing all of x (running minimum).

    Normal mixture N(mu0, tau^2) over the alternative, sigma plugged in from the data (or
    given). tau defaults to sigma: the size of effect the test is tuned to find fastest.
    """
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 2:
        return 1.0
    s = float(sigma) if sigma else float(a.std(ddof=1))
    if s <= 0:
        return 1.0
    t = float(tau) if tau else s
    p = 1.0
    csum = np.cumsum(a - mu0)
    s2, t2 = s * s, t * t
    for n in range(1, len(a) + 1):
        d = csum[n - 1] / n
        log_lr = 0.5 * math.log(s2 / (s2 + n * t2)) + (n * n * t2 * d * d) / (2 * s2 * (s2 + n * t2))
        p = min(p, math.exp(-log_lr) if log_lr < 700 else 0.0)
    return float(min(1.0, p))


def sequential_verdict(x, worthwhile: float, alpha: float = 0.05, min_obs: int = 10,
                       tau: float | None = None) -> dict:
    """IN, OUT or OPEN for a stream of forward returns (each one trade or one period).

    IN : the mean is credibly above 0 (always-valid p for mean == 0 below alpha, mean > 0).
    OUT: the mean is credibly below `worthwhile`, the smallest edge worth keeping
         (always-valid p for mean == worthwhile below alpha, mean < worthwhile).
    Both tests are always valid, so checking after every observation is allowed.
    """
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    n = len(a)
    if n < min_obs:
        return {"verdict": "OPEN", "n": n, "p_edge": 1.0, "p_short": 1.0, "mean": float(a.mean()) if n else 0.0}
    m = float(a.mean())
    p_edge = msprt_p(a, 0.0, tau)
    p_short = msprt_p(a, worthwhile, tau)
    v = "OPEN"
    if m > 0 and p_edge < alpha:
        v = "IN"
    elif m < worthwhile and p_short < alpha:
        v = "OUT"
    return {"verdict": v, "n": n, "mean": m, "p_edge": round(p_edge, 5), "p_short": round(p_short, 5)}


# --------------------------------------------------------------------------- bandit
def thompson_pick(cands: list[dict], k: int, seed: int | None = None) -> list[str]:
    """Pick k candidate ids for the demo slots by Thompson sampling.

    Each cand: {"id", "prior_mean", "prior_sd", "n", "mean", "sd"} about the mean return per
    decision period. Normal prior x Normal likelihood (sd plugged in) -> Normal posterior; draw
    once from each, keep the k largest draws. Candidates with little forward data keep wide
    posteriors, so they still win slots sometimes: exploration without a tuning knob.
    """
    rng = np.random.default_rng(seed)
    draws = []
    for c in cands:
        pv = max(float(c.get("prior_sd") or 1e-6), 1e-9) ** 2
        n = int(c.get("n") or 0)
        sd = float(c.get("sd") or 0) or math.sqrt(pv)
        if n > 0:
            post_v = 1.0 / (1.0 / pv + n / (sd * sd))
            post_m = post_v * (float(c.get("prior_mean") or 0) / pv + n * float(c.get("mean") or 0) / (sd * sd))
        else:
            post_v, post_m = pv, float(c.get("prior_mean") or 0)
        draws.append((rng.normal(post_m, math.sqrt(post_v)), c["id"]))
    draws.sort(reverse=True)
    return [cid for _, cid in draws[:k]]


# --------------------------------------------------------------------------- ruin
def ruin_probability(r_multiples, risk_usd: float, equity: float, floor: float,
                     max_drawdown: float, n_trades: int = 250, sims: int = 4000,
                     seed: int = 7) -> dict:
    """Chance the account trips its safety switch within n_trades, by bootstrap.

    Each trade wins or loses r * risk_usd, with r drawn from the observed R multiples (loss of
    the full stop = -1). Ruin = equity at or below the floor, or drawdown from peak at or past
    max_drawdown: the two conditions that latch `halted` for good.
    """
    r = np.asarray(r_multiples, dtype=float)
    r = r[np.isfinite(r)]
    if not len(r) or risk_usd <= 0:
        return {"p_ruin": None, "why": "no trade history to resample"}
    rng = np.random.default_rng(seed)
    pnl = rng.choice(r, size=(sims, n_trades)) * risk_usd
    eq = equity + np.cumsum(pnl, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.full((sims, 1), equity), eq], axis=1), axis=1)[:, 1:]
    dd = (peak - eq) / peak
    ruined = ((eq <= floor) | (dd >= max_drawdown)).any(axis=1)
    return {"p_ruin": float(ruined.mean()), "sims": sims, "n_trades": n_trades,
            "risk_usd": round(risk_usd, 2), "equity": round(equity, 2)}
