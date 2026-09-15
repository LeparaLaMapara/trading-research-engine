"""Ornstein-Uhlenbeck mean reversion, with parameters ESTIMATED from data.

This is the first rung where the project stops hand-picking a lookback window and lets the
data choose. It is deliberately the simplest possible member of that class, because the
complexity ladder says a more complex model only earns its place by beating a simpler one
out of sample after costs and after multiple-testing correction.

The mathematics, stated plainly so it can be checked rather than believed.

An OU process is the continuous-time model of something pulled back towards a level:

    dX = theta * (mu - X) dt + sigma dW

    mu     the level it is pulled towards
    theta  how hard it is pulled (larger = faster reversion)
    sigma  how much it is kicked around

Sampled at fixed intervals, an OU process is exactly an AR(1):

    X[t+1] - X[t] = a + b * X[t] + eps,   with  b = -theta * dt

So theta is estimated by one ordinary least squares regression of the change on the level,
which is the standard discrete estimator (Vasicek's, and the same one used to fit pairs
spreads). From it:

    mu         = -a / b
    half_life  = -ln(2) / b        bars for a deviation to decay by half

**The half-life is the whole point.** It is the model's own statement of the horizon it
believes in, estimated rather than assumed. The trading window is set from it instead of
from a number a human liked the look of.

The position rule is then the obvious one: short when far above the fitted level, long when
far below, flat inside the band, with the deviation measured in standard deviations of the
fitted residuals.

Honest limitations, because this is a research system:

* It assumes the level is stationary over the fit window. `analysis/assumptions.py` already
  tests that, and a failed test should kill the candidate before it reaches a backtest.
* A positive `b` means no mean reversion was found at all. The model refuses to trade in
  that case rather than inverting itself into a trend follower, which would be a different
  hypothesis wearing this one's clothes.
* Estimating parameters is exactly where lookahead enters. It is only honest under
  `backtest.walkforward.walk_forward_refit`, which refits before each test window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import FittedStrategy

# A half-life outside this range is not a tradable mean-reversion horizon on H1 bars: below
# it the signal is noise at this sampling rate, above it the position is held so long that
# the stationarity assumption stops being credible.
MIN_HALF_LIFE_BARS = 2.0
MAX_HALF_LIFE_BARS = 500.0


class OUReversion(FittedStrategy):
    """Mean reversion whose horizon and level are estimated, not assumed."""

    def __init__(self, entry_z: float = 1.5, exit_z: float = 0.5) -> None:
        # These two are still chosen rather than fitted, and that is a deliberate limit on
        # this rung: only the PROCESS is estimated here, not the trading thresholds. Fitting
        # the thresholds as well multiplies the search space and belongs on a higher rung,
        # under a bar that has been raised to match.
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.name = f"ou_reversion(entry={entry_z},exit={exit_z})"
        self.fitted_params: dict | None = None

    # ---------------------------------------------------------------- fitting

    def fit(self, train_bars: pd.DataFrame) -> "OUReversion":
        """Estimate theta, mu, sigma and the half-life by OLS of the change on the level."""
        x = np.asarray(train_bars["close"], dtype=float)
        if len(x) < 30:
            self.fitted_params = {"tradable": False, "reason": "not enough history to fit"}
            return self

        lag, delta = x[:-1], np.diff(x)
        # delta = a + b * lag + eps
        b, a = np.polyfit(lag, delta, 1)

        if b >= 0:
            # No pull back towards a level. Refuse rather than silently becoming a trend
            # follower, which is a different hypothesis and must be tested as one.
            self.fitted_params = {"tradable": False, "reason": "no mean reversion found",
                                  "b": float(b)}
            return self

        half_life = float(-np.log(2.0) / b)
        mu = float(-a / b)
        resid = delta - (a + b * lag)
        sigma = float(np.std(resid, ddof=2))

        tradable = (MIN_HALF_LIFE_BARS <= half_life <= MAX_HALF_LIFE_BARS
                    and sigma > 0 and np.isfinite(mu))
        self.fitted_params = {
            "tradable": bool(tradable),
            "theta": float(-b), "mu": mu, "sigma": sigma,
            "half_life_bars": half_life,
            # The window the MODEL chose. Rounded into a usable integer lookback.
            "window": int(max(MIN_HALF_LIFE_BARS, min(half_life * 2.0, MAX_HALF_LIFE_BARS))),
            "n_train": int(len(x)),
        }
        if not tradable:
            self.fitted_params["reason"] = f"half-life {half_life:.1f} bars outside usable range"
        return self

    # ---------------------------------------------------------------- predicting

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Positions from the FITTED parameters only, shifted so bar t uses data to t-1."""
        if not self.fitted_params or not self.fitted_params.get("tradable"):
            return pd.Series(0.0, index=bars.index)

        window = int(self.fitted_params["window"])
        close = bars["close"].astype(float)
        # The level is re-centred on a rolling window whose LENGTH came from the fit. The
        # fitted mu is not used directly as a constant: over a test window months after the
        # fit, a fixed level would be stale and every bar would sit on one side of it.
        level = close.rolling(window, min_periods=window).mean()
        spread = close - level
        scale = spread.rolling(window, min_periods=window).std()

        z = (spread / scale).replace([np.inf, -np.inf], np.nan)
        pos = pd.Series(np.nan, index=bars.index, dtype=float)
        pos[z <= -self.entry_z] = 1.0      # far below the level: expect a pull up
        pos[z >= self.entry_z] = -1.0      # far above: expect a pull down
        pos[z.abs() <= self.exit_z] = 0.0  # back near the level: flat
        pos = pos.ffill().fillna(0.0)
        # The no-lookahead rule: the position HELD during bar t is decided at t-1's close.
        return pos.shift(1).fillna(0.0)

    def economic_rationale(self) -> str:
        return ("A price pushed away from its recent level by temporary order flow tends to "
                "be pulled back by liquidity providers who profit from supplying the other "
                "side; the estimated half-life says how quickly, and the position is only "
                "taken when the deviation is large relative to the noise.")
