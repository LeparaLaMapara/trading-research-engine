"""How many instruments, and which ones? Measured, not assumed.

The case for breadth is arithmetic, not taste. For equally weighted streams with average
correlation rho, the portfolio's Sharpe is the single-stream Sharpe multiplied by

    IDM = sqrt( N / (1 + (N-1) * rho) )

which is exactly `1 / sqrt(w' C w)` for the equal-weight vector, so the same function
handles unequal weights and a full correlation matrix without a separate formula.

Carver's published table (single-instrument Sharpe 0.35 rising to 0.70 across 37 futures
markets) is this expression at rho = 0.233. Two things follow, and they pull in opposite
directions:

  * Breadth is the only free lunch here. Going from one instrument to eight lifts Sharpe
    by about three quarters, without needing a better signal.
  * It saturates fast. Eight to thirty-seven adds barely 0.09. **Most of the benefit has
    arrived by roughly eight near-independent streams**, so the target is five to ten
    uncorrelated ideas, not fifty indicators on one chart.

The word doing the work is *near-independent*. Eight FX majors are not eight streams: they
share the dollar, so rho is high and the multiplier collapses towards one. This module
therefore never assumes rho. It measures the correlation matrix from the bars actually
held, picks a maximally independent subset, and reports what the multiplier really is for
that basket. Where Carver's 0.233 came from 37 genuinely different futures markets, a
basket drawn from a 24-instrument universe spanning FX, metals, indices, energy and crypto
will measure its own number, and that number is the one worth believing.

Nothing here decides anything. It reports, so the choice of basket is made against
measured correlation rather than a hunch about what feels diversified.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Carver's average correlation across 37 futures markets. A reference point, never a default.
CARVER_RHO = 0.233
#: Carver's measured single-instrument Sharpe for a simple trend rule, after costs.
CARVER_SINGLE_SHARPE = 0.35
#: Where the curve flattens. Past this, extra instruments buy very little.
PRACTICAL_BREADTH = 8


def returns_frame(bars_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Align per-symbol bars on their shared timestamps and return simple bar returns.

    The INTERSECTION of timestamps is used deliberately. Instruments trade different
    sessions (an index against crypto, say), and forward-filling a closed market into an
    open one manufactures a correlation that no portfolio could ever have harvested.
    """
    cols = {}
    for symbol, bars in bars_by_symbol.items():
        if bars is None or bars.empty or "close" not in bars:
            continue
        b = bars.sort_values("ts_utc").drop_duplicates("ts_utc")
        s = pd.Series(b["close"].to_numpy(dtype=float), index=pd.Index(b["ts_utc"]))
        cols[symbol] = s.pct_change()
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).dropna(how="any")


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr().fillna(0.0)


def average_correlation(corr: pd.DataFrame) -> float:
    """Mean of the off-diagonal entries. The single number Carver's table turns on."""
    n = len(corr)
    if n < 2:
        return 0.0
    m = corr.to_numpy(dtype=float)
    off = m[~np.eye(n, dtype=bool)]
    return float(np.mean(off))


def diversification_multiplier(corr: pd.DataFrame, weights: np.ndarray | None = None) -> float:
    """IDM = 1 / sqrt(w' C w). Equal weights when none are given.

    Clipped at 1.0 from below: a basket can never be worse than its own average stream
    under this model, and a negative-definite estimate from short history should not be
    reported as a penalty it did not earn.
    """
    n = len(corr)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    w = np.full(n, 1.0 / n) if weights is None else np.asarray(weights, dtype=float)
    w = w / w.sum()
    var = float(w @ corr.to_numpy(dtype=float) @ w)
    if var <= 0:
        return float(np.sqrt(n))        # degenerate estimate: cap at the independent case
    return max(1.0, float(1.0 / np.sqrt(var)))


def portfolio_sharpe(single_sharpe: float, corr: pd.DataFrame,
                     weights: np.ndarray | None = None) -> float:
    """What a basket of equally good streams is worth, given how correlated they are."""
    return single_sharpe * diversification_multiplier(corr, weights)


def effective_corr(corr: pd.DataFrame) -> pd.DataFrame:
    """Absolute correlations, which is what a direction-agnostic rule actually faces.

    For a PORTFOLIO of fixed long positions, a correlation of -0.95 genuinely reduces
    variance. For a basket of TRADING RULES it does not. A trend rule on two instruments
    that move oppositely goes long one and short the other, so the two strategy return
    streams end up about +0.95 correlated: the same bet twice, not two bets. Selecting on
    signed correlation would therefore load the basket with mirror images and call it
    diversification.

    So everything downstream reasons about |rho|. This is a modelling choice with a cost:
    it understates the benefit for a rule that really is direction-locked. When strategy
    returns themselves are available, correlate THOSE and skip this function.
    """
    arr = corr.abs().to_numpy(dtype=float).copy()   # .values can be read-only; copy first
    np.fill_diagonal(arr, 1.0)
    return pd.DataFrame(arr, index=corr.index, columns=corr.columns)


def select_uncorrelated(corr: pd.DataFrame, k: int) -> list[str]:
    """Greedily grow the basket that maximises the diversification multiplier.

    At each step it adds whichever remaining instrument makes the IDM of the basket
    largest, which is the quantity actually being bought. An earlier version minimised the
    worst pairwise correlation instead. That is a different objective and a worse one: IDM
    depends on the whole matrix through `w' C w`, so a basket with no terrible pair can
    still be beaten by one with a better average, and in testing on independent streams the
    max-min basket lost to an arbitrary subset (2.42 against 2.46). Optimising the thing
    you are measuring is not a refinement here, it is the difference between working and
    not working.

    Operates on `effective_corr`, so a strong negative correlation counts as a shared risk
    factor rather than as independence.
    """
    names = list(corr.columns)
    if k <= 0 or not names:
        return []
    if len(names) == 1:
        return names
    # NOTE: no `if k >= len(names): return names` shortcut. Returning the columns unordered
    # would be a correct SELECTION and a useless ORDER, and breadth_report asks for the whole
    # universe precisely so it can read the order off the front. That shortcut silently
    # turned the recommended basket into file order.
    k = min(k, len(names))
    a = effective_corr(corr)

    # Seed with the least correlated PAIR, then grow by best marginal IDM.
    m = a.to_numpy(dtype=float).copy()
    np.fill_diagonal(m, np.inf)
    i, j = np.unravel_index(np.argmin(m), m.shape)
    chosen = [names[int(i)], names[int(j)]]

    while len(chosen) < k:
        best, best_idm = None, -np.inf
        for name in names:
            if name in chosen:
                continue
            trial = chosen + [name]
            idm = diversification_multiplier(a.loc[trial, trial])
            if idm > best_idm:
                best, best_idm = name, idm
        if best is None:
            break
        chosen.append(best)
    return chosen


@dataclass(frozen=True)
class BreadthReport:
    order: list[str]
    rho: float
    idm: float
    single_sharpe: float
    table: list[dict]           # one row per basket size, in selection order

    def to_dict(self) -> dict:
        return {"order": self.order, "rho": round(self.rho, 4), "idm": round(self.idm, 4),
                "single_sharpe": self.single_sharpe, "table": self.table}


def breadth_report(corr: pd.DataFrame, single_sharpe: float = CARVER_SINGLE_SHARPE,
                   max_k: int | None = None) -> BreadthReport:
    """Carver's table, rebuilt on the measured correlations of THIS universe.

    `single_sharpe` is what one stream is worth on its own. It defaults to Carver's 0.35
    because this project has not yet measured a positive one of its own, and saying so is
    more useful than substituting an optimistic guess.
    """
    max_k = max_k or len(corr)
    corr = effective_corr(corr)          # select and measure on the SAME matrix
    order = select_uncorrelated(corr, max_k)
    rows = []
    for n in range(1, len(order) + 1):
        sub = corr.loc[order[:n], order[:n]]
        idm = diversification_multiplier(sub)
        rows.append({"n": n, "added": order[n - 1], "rho": round(average_correlation(sub), 4),
                     "idm": round(idm, 4), "sharpe": round(single_sharpe * idm, 4)})
    full = corr.loc[order, order] if order else corr
    return BreadthReport(order, average_correlation(full), diversification_multiplier(full),
                         single_sharpe, rows)


def noise_floor_idm(k: int, n_obs: int) -> float:
    """The IDM that k GENUINELY INDEPENDENT streams would show on n_obs observations.

    sqrt(k) is the textbook answer and it is unreachable here. `effective_corr` takes
    absolute values, and the sample correlation of two independent series is not zero but
    a draw from roughly N(0, 1/sqrt(T)); its absolute value has mean sqrt(2/(pi*T)). So
    finite data shows a small positive average |rho| even when the truth is zero, and the
    multiplier sits below sqrt(k) by an amount that depends only on how much history there
    is.

    This is the honest bar. A basket whose out-of-sample IDM merely reaches this floor has
    demonstrated nothing beyond what independent noise would have produced.
    """
    if k <= 1 or n_obs <= 1:
        return 1.0
    expected_abs_rho = float(np.sqrt(2.0 / (np.pi * n_obs)))
    return float(np.sqrt(k / (1.0 + (k - 1) * expected_abs_rho)))


def out_of_sample_idm(returns: pd.DataFrame, k: int,
                      train_fraction: float = 0.5) -> dict:
    """Pick the basket on the first half of history, MEASURE it on the second.

    Why this exists. `select_uncorrelated` chooses the instruments whose measured
    correlations look smallest, and measured correlations carry estimation error of roughly
    1/sqrt(T). Searching 276 pairs for the smallest one reliably finds the pairs whose
    error happened to point down, so the IDM computed on the same data used to choose is
    biased UPWARD. The tell is unmistakable: an in-sample IDM above sqrt(k), the value for
    perfectly independent streams, is not diversification, it is noise being selected.

    This is the identical error the walk-forward exists to prevent for strategies, so it
    gets the identical treatment. The out-of-sample number is the one to believe, and the
    gap between the two is the size of the selection bias.
    """
    out = {"k": k, "independent_reference": float(np.sqrt(min(k, returns.shape[1]))),
           "order": [], "in_sample_idm": 0.0, "out_of_sample_idm": 0.0,
           "n_train": 0, "n_test": 0, "evaluable": False,
           "why_not": "", "selection_bias": 0.0, "noise_floor_idm": 0.0,
           "idm_vs_floor": 0.0}
    if returns.empty or returns.shape[1] < 2:
        out["why_not"] = "need at least two instruments"
        return out

    cut = int(len(returns) * train_fraction)
    train, test = returns.iloc[:cut], returns.iloc[cut:]
    if len(train) < 100 or len(test) < 100:
        out["why_not"] = (f"{len(train)} train / {len(test)} test observations; "
                          f"need 100 of each for a correlation worth splitting")
        return out

    train_c = effective_corr(correlation_matrix(train))
    order = select_uncorrelated(train_c, k)
    in_c = train_c.loc[order, order]
    oos_c = effective_corr(correlation_matrix(test)).loc[order, order]
    out.update({
        "order": order, "evaluable": True,
        "n_train": len(train), "n_test": len(test),
        "in_sample_idm": diversification_multiplier(in_c),
        "out_of_sample_idm": diversification_multiplier(oos_c),
    })
    out["selection_bias"] = out["in_sample_idm"] - out["out_of_sample_idm"]
    floor = noise_floor_idm(len(order), len(test))
    out["noise_floor_idm"] = floor
    # Reported as a RATIO, not a pass/fail flag. For genuinely independent streams the
    # out-of-sample multiplier scatters around the floor, so "did it beat the floor" is
    # close to a coin toss and would be read as evidence when it is noise. A ratio near
    # 1.0 means the basket did no better than independence; meaningfully above 1.0 would
    # require negative average |rho|, which real instruments do not have.
    out["idm_vs_floor"] = (out["out_of_sample_idm"] / floor) if floor else 0.0
    return out
