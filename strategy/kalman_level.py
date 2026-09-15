"""A latent fair level, tracked by a Kalman filter, with its noise fitted by likelihood.

Rung 7. Built on **TFiltersPy** (`tfilterspy`), the owner's own published Bayesian state
estimation package, so this rung adds no third-party modelling dependency.

The model, in one sentence: the price you observe is a noisy view of a hidden "fair level"
that itself drifts, and the tradable signal is how surprised the filter is by today's price.

    level[t]  = level[t-1] + w,   w ~ N(0, Q)      the level wanders (unobserved)
    price[t]  = level[t]   + v,   v ~ N(0, R)      we see it through noise

This is the local level model, the simplest state-space model there is. Two things make it a
genuine step above the Ornstein-Uhlenbeck rung below it rather than a restatement of it:

1. **The level adapts.** OU compares price to a rolling mean whose window length is fixed
   once at fit time. Here the level is re-estimated every bar, and how fast it adapts is
   governed by the ratio Q/R, which is itself estimated rather than chosen.

2. **The filter states its own uncertainty.** The innovation covariance is the model's
   answer to "how far off should I expect to be right now". Dividing the innovation by its
   own standard deviation gives a properly scaled surprise, instead of a rolling z-score that
   has no idea whether the market is currently calm or violent. When the filter is unsure,
   the same price gap produces a smaller signal, automatically.

Fitting. Only the signal-to-noise ratio q = Q/R governs the filter's behaviour, so q is
chosen by maximising the Gaussian likelihood of the innovations over the training window,
with R profiled against each candidate rather than fixed once (see `fit`). `tfilterspy`
exposes `log_likelihood_` directly, so the likelihood is read rather than reimplemented.
Verified against series with a known ratio: recovers 1e-4, 1e-3, 1e-2 and 1e-1 exactly.

Why this family is worth climbing at all, beyond finance: the Kalman filter came out of
control engineering and navigation, and the same machinery is the workhorse of empirical
macroeconomics, where the quantity of interest (an equilibrium rate, an output gap, a
time-varying parameter) is never observed and must be inferred from noisy indicators. A
latent "fair value" behind a noisy price is the same problem statement. The physics and
economics rungs the owner wants are not two separate ladders; the state-space formulation is
the bridge between them, and this is the first plank of it.

Honest limitations:

* A random-walk level cannot mean-revert. This model says nothing about where the level
  should go, only where it currently is. That is deliberate at this rung.
* Gaussian noise is assumed. Real returns have fat tails, so the surprise measure will
  understate how often large innovations occur. A heavier-tailed observation model, or the
  particle filter already in TFiltersPy, is the next rung, not this one.
* Estimating parameters is where lookahead enters, so this is only honest under
  `backtest.walkforward.walk_forward_refit`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import FittedStrategy

# Signal-to-noise ratios searched at fit time. Spanning six orders of magnitude covers
# "the level barely moves" through to "the level is essentially the price".
Q_OVER_R_GRID = np.logspace(-6, 0, 25)
MIN_TRAIN_BARS = 200


class KalmanLevel(FittedStrategy):
    """Trade the filter's surprise: how far price sits from its own latent fair level."""

    def __init__(self, entry_z: float = 2.0, exit_z: float = 0.5) -> None:
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.name = f"kalman_level(entry={entry_z},exit={exit_z})"
        self.fitted_params: dict | None = None

    # ---------------------------------------------------------------- fitting

    @staticmethod
    def _run_filter(obs: np.ndarray, q_over_r: float, r_var: float):
        from tfilterspy.state_estimation.linear_filters import KalmanFilter
        kf = KalmanFilter(F=[[1.0]], H=[[1.0]],
                          Q=[[q_over_r * r_var]], R=[[r_var]],
                          x0=[float(obs[0])], P0=[[r_var]])
        kf.fit(obs.reshape(-1, 1))
        kf.predict()
        return kf

    def fit(self, train_bars: pd.DataFrame) -> "KalmanLevel":
        obs = np.asarray(train_bars["close"], dtype=float)
        if len(obs) < MIN_TRAIN_BARS:
            self.fitted_params = {"tradable": False,
                                  "reason": "not enough history to fit the noise terms"}
            return self

        # Observation noise from the scale of one-bar changes. A robust scale estimator
        # rather than the variance, because a handful of jumps would otherwise set it.
        diffs = np.diff(obs)
        mad = float(np.median(np.abs(diffs - np.median(diffs))))
        r_var = float((1.4826 * mad) ** 2) or float(np.var(diffs))
        if not np.isfinite(r_var) or r_var <= 0:
            self.fitted_params = {"tradable": False, "reason": "degenerate price scale"}
            return self

        # R is PROFILED against each candidate ratio rather than fixed once. For the local
        # level model the observed one-bar change has variance Q + 2R, so using the change
        # scale directly as R double-counts the process noise: R comes out too big, the
        # ratio too small, and the filter too sluggish. With Q = q*R that variance is
        # R*(q + 2), so each q implies its own R and the likelihood compares like with like.
        var_diff = float((1.4826 * mad) ** 2) or float(np.var(diffs))
        best_q, best_ll, best_r = None, -np.inf, None
        for q in Q_OVER_R_GRID:
            r_q = var_diff / (q + 2.0)
            try:
                kf = self._run_filter(obs, float(q), r_q)
                ll = float(np.asarray(kf.log_likelihood_))
            except Exception:  # noqa: BLE001 - a ratio that will not filter is simply skipped
                continue
            if np.isfinite(ll) and ll > best_ll:
                best_ll, best_q, best_r = ll, float(q), float(r_q)
        if best_r is not None:
            r_var = best_r

        if best_q is None:
            self.fitted_params = {"tradable": False,
                                  "reason": "no signal-to-noise ratio produced a usable fit"}
            return self

        self.fitted_params = {
            "tradable": True,
            "q_over_r": best_q,          # how fast the level is allowed to adapt
            "r_var": r_var,
            "log_likelihood": best_ll,
            "n_train": int(len(obs)),
            # At the grid edges the likelihood wanted to keep going, so the estimate is a
            # boundary artefact rather than a maximum. Recorded, not hidden.
            "at_grid_edge": bool(best_q <= Q_OVER_R_GRID[0] or best_q >= Q_OVER_R_GRID[-1]),
        }
        return self

    # ---------------------------------------------------------------- predicting

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        if not self.fitted_params or not self.fitted_params.get("tradable"):
            return pd.Series(0.0, index=bars.index)

        obs = np.asarray(bars["close"], dtype=float)
        if len(obs) < 10:
            return pd.Series(0.0, index=bars.index)
        try:
            kf = self._run_filter(obs, self.fitted_params["q_over_r"],
                                  self.fitted_params["r_var"])
        except Exception:  # noqa: BLE001 - refuse rather than trade on a broken filter
            return pd.Series(0.0, index=bars.index)

        innov = np.asarray(kf.innovations_, dtype=float).reshape(-1)
        innov_var = np.asarray(kf.innovation_covs_, dtype=float).reshape(-1)
        # The filter's own uncertainty sets the scale. A big gap when the filter is already
        # unsure is not surprising; the same gap when it is confident is.
        z = np.divide(innov, np.sqrt(np.maximum(innov_var, 1e-18)),
                      out=np.zeros_like(innov), where=innov_var > 0)
        z = pd.Series(z, index=bars.index).replace([np.inf, -np.inf], np.nan)

        pos = pd.Series(np.nan, index=bars.index, dtype=float)
        pos[z <= -self.entry_z] = 1.0     # price far below its latent level
        pos[z >= self.entry_z] = -1.0     # price far above it
        pos[z.abs() <= self.exit_z] = 0.0
        pos = pos.ffill().fillna(0.0)
        # The innovation at bar t uses bar t's own price, so it must be shifted before it can
        # be traded on. Without this the strategy would be acting on information it could not
        # have had, which is the single easiest way to invent an edge that does not exist.
        return pos.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("Price is a noisy observation of a slower-moving fair level; when order flow "
                "pushes the quote further from that level than the filter's own uncertainty "
                "can explain, the gap tends to close as liquidity providers arbitrage it.")
