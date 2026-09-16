"""Reject a rule for being too expensive BEFORE it is fitted, scored, or ranked.

Everything in this project already charges costs. The harness deducts them on every
position change and the walk-forward scores net returns. So why add this?

Because charging a cost AFTER the fact and rejecting a rule BEFORE the fact are different
mechanisms with different failure modes. When an expensive rule is allowed into the
tournament, it competes: it can win on a lucky draw, its parameters get optimised against
net returns, and the optimiser's easiest way to recover a large cost drag is to find a
fold where the noise happened to pay for it. That is not a strategy, it is a rule whose
costs were fitted away. Carver's remedy is blunt and it is the right one: estimate what
the rule costs to run, and if it costs more than a fixed ceiling, DELETE IT. Do not
optimise it, do not score it, do not let it into the leaderboard.

The unit is Sharpe-ratio-units per year, which makes the ceiling comparable across
instruments and speeds:

    annual cost drag (return)  /  annualised volatility (return)  =  cost in SR units

A rule whose costs eat 0.13 of annual Sharpe is at the ceiling. That number is Carver's,
derived from systematic futures trading, and it is deliberately strict: a realistic
pre-cost Sharpe for a retail-accessible rule is somewhere around 0.3 to 0.5, so 0.13 is
already a quarter to a half of everything the rule could ever earn.

**On lookahead.** Estimating turnover needs signals, and a fitted strategy needs to be fit
before it has any. The probe therefore fits and measures on the TRAINING PORTION ONLY
(`train_fraction`, default the first half). This matters less than it looks: the number
produced here is used ONLY to reject, never to score. Lookahead in a rejection test can
cost you a good rule; it cannot manufacture a good result. The scoring path is untouched
and still runs through `walk_forward_refit`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.harness import CostModel
from backtest.metrics import BARS_PER_YEAR
from strategy.base import FittedStrategy, Strategy

#: Carver's cost ceiling, in annual Sharpe-ratio units. A rule above this is deleted.
COST_CEILING_SR = 0.13

#: Below this many bars the turnover estimate is noise, so the probe declines to judge.
MIN_PROBE_BARS = 60


@dataclass(frozen=True)
class CostEstimate:
    """What running this rule costs, and whether that is affordable.

    `evaluable` False means the probe could not form an opinion (too little history, or a
    rule that never takes a position). That is NOT a rejection: unknown is not failed, the
    same rule the walk-forward already follows.
    """
    evaluable: bool
    affordable: bool
    cost_sr: float              # annual cost drag in Sharpe units
    ceiling_sr: float
    turnover_per_bar: float     # mean |delta position|
    annual_cost_return: float   # cost drag as an annual return fraction
    annual_vol: float           # annualised volatility of the rule's gross returns
    reason: str

    def to_dict(self) -> dict:
        return {"evaluable": self.evaluable, "affordable": self.affordable,
                "cost_sr": round(self.cost_sr, 4), "ceiling_sr": self.ceiling_sr,
                "turnover_per_bar": round(self.turnover_per_bar, 5),
                "annual_cost_return": round(self.annual_cost_return, 6),
                "annual_vol": round(self.annual_vol, 6), "reason": self.reason}


def cost_in_sharpe_units(positions: pd.Series, bar_returns: pd.Series, costs: CostModel,
                         period: str) -> tuple[float, float, float, float]:
    """(cost_sr, turnover_per_bar, annual_cost_return, annual_vol) for a held position path.

    Volatility is the rule's OWN gross return volatility, not the instrument's. A rule that
    sits flat most of the time has both low cost and low volatility, and dividing one by the
    other is what stops the ceiling from quietly favouring rules that simply do nothing.
    """
    ppy = float(BARS_PER_YEAR.get(period.upper(), 6240))
    pos = positions.astype(float).fillna(0.0)
    ret = bar_returns.astype(float).fillna(0.0)

    # First bar costs a full entry: there is no free position.
    turnover = pos.diff().abs().fillna(pos.abs())
    turnover_per_bar = float(turnover.mean())
    annual_cost = turnover_per_bar * costs.cost_per_unit_turnover() * ppy

    gross = pos * ret
    annual_vol = float(gross.std(ddof=0) * np.sqrt(ppy))
    if annual_vol <= 0:
        return float("inf"), turnover_per_bar, annual_cost, 0.0
    return annual_cost / annual_vol, turnover_per_bar, annual_cost, annual_vol


def probe_cost(bars: pd.DataFrame, make_strategy, costs: CostModel, period: str,
               ceiling_sr: float = COST_CEILING_SR,
               train_fraction: float = 0.5) -> CostEstimate:
    """Estimate what this rule costs to run, using the training portion only.

    `make_strategy` is a zero-argument callable returning a fresh strategy, the same
    contract `walk_forward_refit` uses, so a fitted rule is fit here on train data alone.
    """
    if len(bars) < MIN_PROBE_BARS:
        return CostEstimate(False, True, 0.0, ceiling_sr, 0.0, 0.0, 0.0,
                            f"only {len(bars)} bars, need {MIN_PROBE_BARS} to estimate "
                            f"turnover")

    bars = bars.sort_values("ts_utc").reset_index(drop=True)
    cut = max(MIN_PROBE_BARS, int(len(bars) * train_fraction))
    train = bars.iloc[:cut].reset_index(drop=True)

    strat: Strategy = make_strategy()
    if isinstance(strat, FittedStrategy):
        strat.fit(train)
        if not strat.is_fitted():
            return CostEstimate(False, True, 0.0, ceiling_sr, 0.0, 0.0, 0.0,
                                "strategy did not fit on the training window")
    try:
        positions = strat.generate_signals(train).astype(float)
    except Exception as exc:                        # a rule that cannot run is not a cost problem
        return CostEstimate(False, True, 0.0, ceiling_sr, 0.0, 0.0, 0.0,
                            f"could not generate signals: {type(exc).__name__}: {exc}")

    if len(positions) != len(train):
        return CostEstimate(False, True, 0.0, ceiling_sr, 0.0, 0.0, 0.0,
                            "signal length does not match the training window")

    active = int((positions.fillna(0.0) != 0).sum())
    if active == 0:
        return CostEstimate(False, True, 0.0, ceiling_sr, 0.0, 0.0, 0.0,
                            "rule never takes a position on the training window")

    bar_returns = train["close"].pct_change().fillna(0.0)
    cost_sr, tpb, annual_cost, annual_vol = cost_in_sharpe_units(positions, bar_returns,
                                                                 costs, period)
    affordable = cost_sr <= ceiling_sr
    if affordable:
        reason = (f"costs {cost_sr:.3f} Sharpe units/year, within the {ceiling_sr:.2f} "
                  f"ceiling")
    else:
        reason = (f"costs {cost_sr:.3f} Sharpe units/year, above the {ceiling_sr:.2f} "
                  f"ceiling: it turns over {tpb:.3f} per bar, which is "
                  f"{annual_cost * 100:.1f}% a year against {annual_vol * 100:.1f}% "
                  f"volatility. Too expensive to run, deleted before testing.")
    return CostEstimate(True, affordable, cost_sr, ceiling_sr, tpb, annual_cost, annual_vol,
                        reason)
