"""Explainer (spec §3.5): turn a backtest into plain English a non-expert can read.

States what the strategy bets on, why it should work economically, the numbers, the cost
assumptions those numbers depend on, and — loudly — what this is NOT. The caveats are not
boilerplate; they are the honest boundary of what a single simple backtest can claim.
"""
from __future__ import annotations

from backtest.harness import BacktestResult, CostModel
from strategy.base import Strategy


def explain(symbol: str, period: str, strategy: Strategy, result: BacktestResult,
            costs: CostModel, n_bars: int, holdout: dict | None = None) -> str:
    s = result.summary
    lines = [
        f"# {strategy.name} on {symbol} {period}  —  pipeline test report",
        "",
        "## What it bets on",
        f"  {strategy.economic_rationale()}",
        "",
        "## Result (AFTER costs), full sample",
        f"  bars tested        {n_bars}",
        f"  Sharpe             {s['sharpe']}      (risk-adjusted return — the objective)",
        f"  Sortino            {s['sortino']}",
        f"  Calmar             {s['calmar']}",
        f"  max drawdown       {s['max_drawdown']*100:.1f}%",
        f"  total return       {s['total_return']*100:.1f}%",
        f"  trades             {s['num_trades']}",
        f"  win rate           {s['win_rate']*100:.0f}%",
        f"  avg trade          {s['avg_trade']*100:.3f}%",
    ]
    if holdout is not None:
        lines += [
            "",
            "## Out-of-sample tail (last 30%, strategy unchanged)",
            f"  Sharpe             {holdout['sharpe']}",
            f"  max drawdown       {holdout['max_drawdown']*100:.1f}%",
            f"  trades             {holdout['num_trades']}",
            "  (If this is far worse than the full sample, the full-sample number is flattered.)",
        ]
    lines += [
        "",
        "## Cost assumptions these numbers depend on",
        f"  spread             {costs.spread_pips:.2f} pips (measured from your own telemetry)",
        f"  commission         {costs.commission_per_side*1e5:.1f} per $100k per side",
        "  Change the spread and these results change. Thin-hour spreads are much worse.",
        "",
        "## What this is NOT (read this)",
        "  - NOT evidence the strategy works. One rule, one symbol, one parameter set.",
        "  - NOT walk-forward validated (only a simple tail split) and NOT multiple-testing",
        "    corrected. A pretty number here is the EXPECTED result of trying, not an edge.",
        "  - NOT permission to trade live. The purpose was to prove the pipeline runs.",
        "  - Spread is modelled from limited telemetry; slippage and rejections are not yet",
        "    included (they need the gated live probe trades).",
    ]
    return "\n".join(lines)
