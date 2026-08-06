"""The research loop, end to end. This is the finished pipeline.

For each round:
  Council PROPOSES a strategy (mock offline, or Claude+Gemini with API keys)
    -> validator rejects prohibited patterns (martingale etc.)     [spec time]
    -> skip if it repeats a logged failure                          [Failure Registry]
    -> Assumption Tester checks the series                          [cheap kill]
    -> Session filter restricts to cheap hours (from telemetry)
    -> Walk-forward backtest with real measured costs               [the ONLY judge]
    -> Deflated Sharpe corrects for how many strategies were tried  [multiple testing]
    -> the committed prediction is SCORED                           [agent calibration]
    -> failures are logged permanently                              [Failure Registry]

The LLMs only propose. Every decision here is deterministic code. Nothing trades live.

Run:  python -m research.experiment --symbol EURUSD --period H1 --rounds 6
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from analysis.assumptions import run_assumptions
from analysis.session_filter import SessionFilter, derive_cheap_hours
from backtest import walkforward as wf
from backtest.metrics import BARS_PER_YEAR
from backtest.run import load_bars, measured_cost
from config import settings
from council.backends import get_backend
from council.orchestrator import Council
from research.calibration import Calibration
from research.registry import FailureRegistry
from strategy.base import Strategy
from strategy.registry import build_strategy, rung_of
from strategy.validator import validate_proposal

MIN_DSR = 0.95           # deflated-Sharpe bar: 95% confident the edge survives multiple testing


class _SessionWrapped(Strategy):
    """Apply the measured session filter on top of any strategy's signals."""
    def __init__(self, inner: Strategy, sfilter: SessionFilter) -> None:
        self.inner = inner
        self.sf = sfilter
        self.name = f"{inner.name}+session"

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return self.sf.apply(bars, self.inner.generate_signals(bars))

    def economic_rationale(self) -> str:
        return self.inner.economic_rationale()


def _actual_metrics(summary: dict, n_bars: int, period: str) -> dict:
    ppy = BARS_PER_YEAR.get(period.upper(), 6240)
    bars_per_month = ppy / 12.0
    return {
        "sharpe": summary["sharpe"],
        "max_drawdown": summary["max_drawdown"],
        "win_rate": summary["win_rate"],
        "trades_per_month": summary["num_trades"] / (n_bars / bars_per_month) if n_bars else 0.0,
    }


def run_experiment(symbol: str, period: str, rounds: int, max_rung: int,
                   min_dsr: float = MIN_DSR, seed: int = 0) -> dict:
    bars = load_bars(symbol, period)
    if bars.empty:
        raise SystemExit(f"no bars for {symbol} {period}. Fetch first: "
                         f"python -m market.bars --symbol {symbol} --period {period}")
    costs = measured_cost(symbol, ref_price=float(bars["close"].mean()))
    allowed = derive_cheap_hours(settings.TELEMETRY_DB, symbol)
    # Only restrict hours once telemetry actually covers a meaningful span. With only a
    # short capture (one hour logged), the "cheap hours" set is tiny and would zero out
    # almost every bar. Until we have real coverage, trade all hours.
    use_session = len(allowed) >= 24
    sfilter = SessionFilter(allowed) if use_session else None
    print(f"[experiment] session filter: "
          f"{'ON, ' + str(len(allowed)) + ' hours' if use_session else 'OFF (telemetry too sparse)'}")

    # Cross-model council: Claude proposes, Gemini red-teams (each falls back to the mock
    # backend if its key is missing). This is the spec's adversarial design.
    council = Council(proposer_backend=get_backend("anthropic"),
                      redteam_backend=get_backend("gemini"))
    registry = FailureRegistry()
    calib = Calibration()

    trials: list[dict] = []
    proposed_this_run: list[dict] = []   # kinds already tried this run -> drives diversity
    for r in range(rounds):
        seen = registry.all()
        # Ask the proposer to avoid both logged failures AND anything already tried this run,
        # so a single run climbs the ladder instead of repeating one favoured kind.
        context = {"symbol": symbol, "period": period, "max_rung": max_rung,
                   "seen_failures": [f for f in seen if f.get("symbol") == symbol]
                   + proposed_this_run}
        committed_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        rd = council.run_round(context, r, committed_at)
        proposal, prediction, critique = rd["proposal"], rd["prediction"], rd["critique"]
        proposed_this_run.append({"strategy_kind": proposal.kind, "symbol": symbol})

        ok, reasons = validate_proposal({"kind": proposal.kind, "params": proposal.params})
        if not ok:
            registry.add(strategy_kind=proposal.kind, symbol=symbol, killed_at_stage="spec",
                         cause_category="prohibited_pattern", plain_english="; ".join(reasons),
                         generalisable_lesson="reject this pattern at spec time",
                         proposing_agent=proposal.agent, created_ts=time.time())
            trials.append({"proposal": proposal, "verdict": "REJECTED", "reason": reasons})
            continue

        if registry.matches(proposal.kind, symbol):
            trials.append({"proposal": proposal, "verdict": "SKIPPED",
                           "reason": ["repeats a logged failure"]})
            continue

        assumptions = run_assumptions(bars["close"])
        base = build_strategy(proposal.kind, proposal.params)
        strat = _SessionWrapped(base, sfilter) if sfilter else base
        wfr = wf.walk_forward(bars, strat, costs, period)

        pred_id = calib.record(prediction)
        actual = _actual_metrics(wfr["dev_summary"], wfr["n_bars"], period)
        calib.score(pred_id, actual)

        trials.append({
            "proposal": proposal, "prediction": prediction, "critique": critique,
            "assumption_verdict": assumptions.get("verdict", ""),
            "wf": wfr, "actual": actual,
            "per_obs_sharpe": wf.per_obs_sharpe(wfr["dev_net_returns"]),
        })

    # Multiple-testing correction needs the spread of Sharpes ACROSS all real trials.
    tested = [t for t in trials if "wf" in t]
    sharpe_std = float(np.std([t["per_obs_sharpe"] for t in tested])) if len(tested) > 1 else 0.1
    for t in tested:
        dsr = wf.deflated_sharpe_ratio(t["wf"]["dev_net_returns"], max(len(tested), 2), sharpe_std)
        t["dsr"] = dsr
        hold = t["wf"]["holdout_summary"]
        hold_sharpe = hold["sharpe"] if hold else 0.0
        passed = dsr >= min_dsr and hold_sharpe > 0 and t["wf"]["dev_summary"]["sharpe"] > 0
        t["verdict"] = "PASS" if passed else "FAIL"
        if not passed:
            cause = ("failed_deflated_sharpe" if dsr < min_dsr
                     else "negative_holdout" if hold_sharpe <= 0 else "negative_dev")
            registry.add(strategy_kind=t["proposal"].kind, symbol=symbol,
                         killed_at_stage="backtest", cause_category=cause,
                         plain_english=f"DSR={dsr:.2f}, dev Sharpe={t['wf']['dev_summary']['sharpe']}, "
                                       f"holdout Sharpe={hold_sharpe}",
                         generalisable_lesson=f"{t['proposal'].kind} did not survive on {symbol}",
                         proposing_agent=t["proposal"].agent, created_ts=time.time())

    return {"symbol": symbol, "period": period, "trials": trials, "tested": tested,
            "registry": registry, "calibration": calib, "sharpe_std": sharpe_std,
            "min_dsr": min_dsr}


def format_report(res: dict) -> str:
    lines = [f"# Research experiment — {res['symbol']} {res['period']}",
             f"(LLMs propose, code decides. Deflated-Sharpe bar = {res['min_dsr']}. "
             f"Nothing traded live.)", "", "## Leaderboard (survivors first)"]
    ranked = sorted(res["tested"], key=lambda t: t.get("dsr", 0), reverse=True)
    if not ranked:
        lines.append("  (no strategies reached the backtest stage)")
    for t in ranked:
        p, w = t["proposal"], t["wf"]
        hold = w["holdout_summary"]["sharpe"] if w["holdout_summary"] else float("nan")
        lines.append(
            f"  [{t['verdict']:<4}] {p.kind:<15} rung{rung_of(p.kind)}  "
            f"devSharpe={w['dev_summary']['sharpe']:>6}  holdout={hold:>6}  "
            f"DSR={t.get('dsr', 0):.2f}  splitσ={w['split_sharpe_std']}  "
            f"maxDD={w['dev_summary']['max_drawdown']*100:.0f}%")
    rejected = [t for t in res["trials"] if t.get("verdict") in ("REJECTED", "SKIPPED")]
    if rejected:
        lines += ["", "## Rejected / skipped before testing"]
        for t in rejected:
            lines.append(f"  [{t['verdict']}] {t['proposal'].kind}: {', '.join(t['reason'])}")

    lines += ["", "## Failure registry (permanent memory)"]
    for cause, n in res["registry"].summary().items():
        lines.append(f"  {cause}: {n}")

    lines += ["", "## Agent calibration (the scoreboard the owner reads)"]
    for agent in sorted({t["proposal"].agent for t in res["tested"]}):
        c = res["calibration"].agent_calibration(agent)
        lines.append(f"  {agent}: predictions={c.get('n_predictions',0)}  "
                     f"field_accuracy={c.get('field_accuracy',0):.2f}  "
                     f"mean_confidence={c.get('mean_confidence',0):.2f}")

    lines += ["", "## Honest boundary",
              "  Survivors are candidates, NOT proven edges: one holdout, modelled costs, no",
              "  live slippage yet. A PASS means 'worth more scrutiny', never 'trade it'."]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Run the end-to-end research experiment loop.")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--period", default="H1")
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--max-rung", type=int, default=5)
    p.add_argument("--min-dsr", type=float, default=MIN_DSR)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    res = run_experiment(args.symbol, args.period, args.rounds, args.max_rung, args.min_dsr, args.seed)
    report = format_report(res)
    print(report)
    with open("data/experiment_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print("\nsaved -> data/experiment_report.txt")


if __name__ == "__main__":
    main()
