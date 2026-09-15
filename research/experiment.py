"""The research loop, end to end. This is the finished pipeline.

For each round:
  Council PROPOSES a strategy (mock offline, or Claude+Gemini with API keys)
    -> validator rejects prohibited patterns (martingale etc.)     [spec time]
    -> skip only an identical re-run, tabu expires, aspiration wins [Failure Registry]
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
import sys
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
from research.lessons import LessonStore, lessons_from_cycle
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


def _paper_proposals(symbol: str, period: str, n: int, committed_at: str):
    """Fetch real papers via the Scout, map to strategies, persist the cards, and build
    StrategyProposals (with falsifiable predictions) for the harness to judge. Real papers
    in, real backtests out; the identifier on every card is a fetched arXiv id."""
    import uuid

    from council.proposer import Proposer
    from research.cards import CardStore
    from research.schemas import StrategyProposal
    from scout.scout import Scout
    from strategy.registry import rung_of

    scout = Scout(backend=get_backend("anthropic"))
    store = CardStore()
    proposer = Proposer(get_backend("mock"))   # used only for its falsifiable-bound defaults
    out = []
    for card in scout.discover(n):
        store.save(card)                        # persist every fetched card (memory + dashboard)
        print(f"[scout] {card.identifier} -> {card.mapped_kind or 'no mapping'}: "
              f"{card.title[:70]}")
        if not card.mapped_kind:
            continue
        p = StrategyProposal(id=str(uuid.uuid4()), kind=card.mapped_kind,
                             params=card.mapped_params or {}, rung=rung_of(card.mapped_kind),
                             symbol=symbol, period=period,
                             agent=f"scout:{card.identifier}", rationale=card.market_claim[:200])
        p.prediction = proposer._prediction_for(p, committed_at)
        out.append((p, p.prediction, {"concerns": [], "source": card.identifier}))
    store.close()
    return out


def _track_record(calib: Calibration, agent: str) -> dict:
    """The agent's own scored history, so it can be told how right it has actually been."""
    try:
        c = calib.agent_calibration(agent)
    except Exception:
        return {}
    n = c.get("n_predictions") or c.get("predictions") or 0
    if not n:
        return {}
    acc = c.get("field_accuracy")
    note = ""
    if acc is not None:
        note = (f"You have committed {n} falsifiable predictions and been right about "
                f"{acc*100:.0f}% of the fields. ")
        if acc < 0.5:
            note += ("You are wrong more often than right, so state weaker claims and say "
                     "plainly when you do not know.")
    return {"n_predictions": n, "field_accuracy": acc, "note": note}


def run_experiment(symbol: str, period: str, rounds: int, max_rung: int,
                   min_dsr: float = MIN_DSR, seed: int = 0, from_papers: int = 0) -> dict:
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

    registry = FailureRegistry()
    calib = Calibration()
    lessons = LessonStore()
    # The playbook shown to the proposer this cycle. Shown now, credited later only if the
    # cycle actually beat the historical best -- that is what makes the win rate mean anything.
    active_lessons = lessons.active()
    shown_fps = [ln["fingerprint"] for ln in active_lessons]
    lessons.mark_shown(shown_fps)
    # Same units on both sides of the comparison. See registry.set_trial_dsr.
    best_before = registry.best_dsr()
    trials: list[dict] = []

    def process(proposal, prediction, critique) -> None:
        """Judge one proposal (from the council or a paper): validate -> registry check ->
        assumption test -> session filter -> walk-forward backtest -> score the prediction."""
        ok, reasons = validate_proposal({"kind": proposal.kind, "params": proposal.params})
        if not ok:
            registry.add(strategy_kind=proposal.kind, symbol=symbol, killed_at_stage="spec",
                         cause_category="prohibited_pattern", plain_english="; ".join(reasons),
                         generalisable_lesson="reject this pattern at spec time",
                         proposing_agent=proposal.agent, created_ts=time.time(),
                         params=proposal.params, period=period, n_bars=len(bars))
            registry.record_trial(proposal.kind, proposal.params, symbol, period, stage="spec")
            trials.append({"proposal": proposal, "verdict": "REJECTED", "reason": reasons})
            return
        # Hard tabu applies to an identical re-run only, and expires. A family that failed once
        # under one parameterisation is NOT blocked -- it is penalised in the proposer context.
        # Aspiration: a candidate whose committed prediction beats the incumbent best runs
        # regardless, so remembered failure can never become a permanent veto.
        best_so_far = max((t["actual"]["sharpe"] for t in trials if "actual" in t), default=0.0)
        predicted = float(getattr(prediction, "sharpe_gt", 0.0) or 0.0)
        aspires = predicted > best_so_far
        skip, why = registry.is_tabu(proposal.kind, proposal.params, symbol, period,
                                     n_bars=len(bars), aspiration=aspires)
        if skip:
            # Counted against N even though it was not re-run: the deflation bar depends on
            # what was TRIED, and a skip that is not counted makes overfitting worse.
            registry.record_trial(proposal.kind, proposal.params, symbol, period, stage="tabu")
            trials.append({"proposal": proposal, "verdict": "SKIPPED", "reason": [why]})
            return
        assumptions = run_assumptions(bars["close"])
        base = build_strategy(proposal.kind, proposal.params)
        strat = _SessionWrapped(base, sfilter) if sfilter else base
        wfr = wf.walk_forward(bars, strat, costs, period)
        pred_id = calib.record(prediction)
        actual = _actual_metrics(wfr["dev_summary"], wfr["n_bars"], period)
        calib.score(pred_id, actual)
        per_obs = wf.per_obs_sharpe(wfr["dev_net_returns"])
        trial_id = registry.record_trial(proposal.kind, proposal.params, symbol, period,
                                         stage="backtest", per_obs_sharpe=per_obs,
                                         n_bars=wfr["n_bars"])
        trials.append({
            "proposal": proposal, "prediction": prediction, "critique": critique,
            "assumption_verdict": assumptions.get("verdict", ""),
            "wf": wfr, "actual": actual,
            "per_obs_sharpe": per_obs, "trial_id": trial_id,
        })

    committed_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    if from_papers > 0:
        # Source proposals from REAL papers the Scout fetched and mapped to strategies.
        for proposal, prediction, critique in _paper_proposals(symbol, period, from_papers,
                                                               committed_at):
            process(proposal, prediction, critique)
    else:
        # Cross-model council: Claude proposes, Gemini red-teams (each falls back to the mock
        # backend if its key is missing). This is the spec's adversarial design.
        council = Council(proposer_backend=get_backend("anthropic"),
                          redteam_backend=get_backend("gemini"))
        proposed_this_run: list[dict] = []   # kinds tried this run -> drives diversity
        for r in range(rounds):
            seen = registry.all()
            # Steer the proposer BEFORE it spends a token: hand it the exact variants already
            # tested and a soft per-family penalty. Previously the skip happened after the
            # proposal came back, so the council was billed for output that was discarded.
            kinds = {f.get("strategy_kind") for f in seen if f.get("symbol") == symbol}
            penalties = {k: round(registry.family_penalty(k, symbol), 2) for k in kinds if k}
            context = {"symbol": symbol, "period": period, "max_rung": max_rung,
                       "seen_failures": [f for f in seen if f.get("symbol") == symbol]
                       + proposed_this_run,
                       "family_penalties": penalties,
                       "tried_variants": [f.get("params_json") for f in seen
                                          if f.get("symbol") == symbol and f.get("params_json")],
                       "guidance": "A family that failed is NOT banned. Propose a genuinely "
                                   "different parameterisation, or a different family, and "
                                   "state the economic mechanism: who is on the other side of "
                                   "this trade and why do they accept the loss.",
                       # What the engine has learned, best-proven first.
                       "lessons": [ln["lesson"] for ln in active_lessons],
                       # The proposer's OWN track record. It has been making falsifiable
                       # predictions and being scored on them since August and had never once
                       # been told the result. An agent that is never shown its errors cannot
                       # correct them.
                       "your_track_record": _track_record(calib, "anthropic")}
            rd = council.run_round(context, r, committed_at)
            proposal, prediction, critique = rd["proposal"], rd["prediction"], rd["critique"]
            proposed_this_run.append({"strategy_kind": proposal.kind, "symbol": symbol})
            process(proposal, prediction, critique)

    # Multiple-testing correction needs the spread of Sharpes ACROSS all real trials.
    tested = [t for t in trials if "wf" in t]
    sharpe_std = float(np.std([t["per_obs_sharpe"] for t in tested])) if len(tested) > 1 else 0.1
    # N is the HONEST trial count: every candidate this engine has ever scored, across every
    # run, not the handful tested in this one. E[max SR] grows with N, so a search that ran
    # thousands of candidates historically must clear a much higher bar than a fresh one.
    # Using len(tested) here (the original bug) understated N by orders of magnitude and made
    # the deflated Sharpe far too easy to pass.
    honest_n = max(registry.effective_n(), len(tested), 2)
    print(f"[experiment] deflating against N={honest_n} candidates ever scored "
          f"({len(tested)} tested this run)")
    for t in tested:
        dsr = wf.deflated_sharpe_ratio(t["wf"]["dev_net_returns"], honest_n, sharpe_std)
        t["dsr"] = dsr
        if t.get("trial_id"):
            registry.set_trial_dsr(t["trial_id"], dsr)
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
                         generalisable_lesson=f"{t['proposal'].kind} did not survive on {symbol} "
                                              f"with params {t['proposal'].params}",
                         proposing_agent=t["proposal"].agent, created_ts=time.time(),
                         params=t["proposal"].params, period=period, n_bars=t["wf"]["n_bars"])

    # --- learning: did this cycle beat anything, and what is worth remembering? --------
    best_now = max((float(t.get("dsr") or 0.0) for t in tested), default=0.0)
    if best_now > best_before:
        # The lessons that were on screen get the credit. Crude attribution, but measured;
        # the alternative is assuming memory helps, which is how memory stores rot.
        lessons.mark_helped(shown_fps)
    for text, evidence in lessons_from_cycle(trials, symbol, honest_n):
        lessons.add(text, evidence, category="cycle")
    retired = lessons.evict()
    if retired:
        print(f"[lessons] retired {len(retired)} lesson(s) that never helped")
    print(f"[lessons] {lessons.summary()}  best DSR before={best_before:.3f} now={best_now:.3f}")

    return {"symbol": symbol, "period": period, "trials": trials, "tested": tested,
            "registry": registry, "calibration": calib, "sharpe_std": sharpe_std,
            "min_dsr": min_dsr, "lessons": lessons, "honest_n": honest_n}


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
    p.add_argument("--from-papers", type=int, default=0,
                   help="source proposals from N real papers the Scout fetches (instead of the council)")
    args = p.parse_args()
    # The report contains sigma and other non-ASCII characters. A Windows console defaults to
    # cp1252 and raises UnicodeEncodeError on them, which killed the run AFTER all the work
    # was done. CI runs UTF-8 so this never showed there.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass
    res = run_experiment(args.symbol, args.period, args.rounds, args.max_rung, args.min_dsr,
                         args.seed, from_papers=args.from_papers)
    report = format_report(res)
    print(report)
    with open("data/experiment_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print("\nsaved -> data/experiment_report.txt")

    # Push results to Supabase for the dashboard (no-op if SUPABASE_* not set).
    from research import supabase_sink
    if supabase_sink.enabled():
        supabase_sink.push_experiment(res)
        print("pushed results to Supabase")


if __name__ == "__main__":
    main()
