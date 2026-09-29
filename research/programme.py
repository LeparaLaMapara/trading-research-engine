"""The research programme: budgets of pre-registered experiments, a running N, and a stop rule.

The rules are in docs/programme/README.md. This module reads docs/programme/register.json,
checks it against git history, and says in plain words where the programme stands.

Since 2026-09-29 the register can hold several programmes (P1, P2, ...). A new one may open
only when the one before it has spent its whole budget, and the count of everything ever tried
(N) carries across all of them: more experiments become possible, but each one is judged
against a higher bar, never a lower one. Audits re-test a rule already counted with stronger
methods; they spend no slot, add nothing to N, and can only demote.

    python -m research.programme
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field

REGISTER = "docs/programme/register.json"
VERDICTS = {None, "PASS", "FAIL"}
KINDS = {"strategy", "measurement", "audit"}


@dataclass
class Status:
    budget: int                      # budget of the current programme
    spent: int                       # current programme's experiments with a verdict
    passed: list[str]                # STRATEGY experiments that passed, current programme
    open: list[str]                  # registered, no verdict yet (any programme, audits too)
    measured: list[str] = field(default_factory=list)   # measurement experiments completed
    problems: list[str] = field(default_factory=list)
    programme: str = "P1"
    n_tried: int = 0                 # everything ever tried: the N every new result must use
    demoted: list[str] = field(default_factory=list)    # rules an audit failed

    @property
    def stop_rule_triggered(self) -> bool:
        return self.spent >= self.budget and not self.passed

    def sentence(self) -> str:
        if self.problems:
            return "The research register has a problem: " + self.problems[0]
        if self.stop_rule_triggered:
            return (f"All {self.budget} experiments of programme {self.programme} are spent and "
                    f"none passed. The stop rule applies: write down that this programme found "
                    f"no edge worth trading.")
        s = (f"Programme {self.programme}: {self.spent} of {self.budget} experiments are done "
             f"and {len(self.passed)} strateg{'y' if len(self.passed) == 1 else 'ies'} passed")
        if self.measured:
            s += f" ({len(self.measured)} of them measured costs rather than tested a strategy)"
        if self.open:
            s += f"; {len(self.open)} in progress ({', '.join(self.open)})"
        s += f". Every new result is judged at N = {self.n_tried} or more"
        if self.demoted:
            s += f". Demoted by an audit: {', '.join(self.demoted)}"
        return s + "."


def _first_commit_ts(path: str, repo: str) -> int | None:
    """Unix time of the commit that first added `path`, or None if it was never committed."""
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%ct", "--", path],
        cwd=repo, capture_output=True, text=True, check=False).stdout.split()
    return int(out[-1]) if out else None


def load(path: str = REGISTER) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def programmes_of(reg: dict) -> list[dict]:
    """The programmes in order. An old register with one top-level budget is programme P1."""
    return reg.get("programmes") or [{"id": "P1", "budget": int(reg.get("budget", 0))}]


def status(reg: dict, repo: str = ".", check_git: bool = True) -> Status:
    progs = programmes_of(reg)
    ids_p = [p["id"] for p in progs]
    current = progs[-1]
    exps = reg.get("experiments", [])
    st = Status(budget=int(current["budget"]), spent=0, passed=[], open=[],
                programme=current["id"], n_tried=int(reg.get("n_before_programme", 0)))
    ids = [e.get("id") for e in exps]
    if len(set(ids)) != len(ids):
        st.problems.append("two experiments share an id.")

    slots: dict[str, list[dict]] = {p: [] for p in ids_p}
    for e in exps:
        pid = e.get("programme", ids_p[0])
        if pid not in slots:
            st.problems.append(f"{e.get('id')} belongs to unknown programme {pid!r}.")
            continue
        kind = e.get("kind", "strategy")
        if kind == "audit":
            if e.get("trials", 0):
                st.problems.append(f"{e.get('id')} is an audit but adds trials; an audit "
                                   f"re-tests a rule already counted.")
        else:
            slots[pid].append(e)
            st.n_tried += int(e.get("trials", 0 if kind == "measurement" else 1))
    for p in progs:
        if len(slots[p["id"]]) > int(p["budget"]):
            st.problems.append(f"{len(slots[p['id']])} experiments registered against programme "
                               f"{p['id']}'s budget of {p['budget']}.")
    for before in progs[:-1]:
        done = [e for e in slots[before["id"]] if e.get("verdict") is not None]
        if len(done) < int(before["budget"]):
            st.problems.append(f"programme {before['id']} was not spent ({len(done)} of "
                               f"{before['budget']}) before a new programme opened.")

    for e in exps:
        eid, verdict, kind = e.get("id"), e.get("verdict"), e.get("kind", "strategy")
        if kind not in KINDS:
            st.problems.append(f"{eid} has an unknown kind {kind!r}.")
            continue
        if verdict not in VERDICTS:
            st.problems.append(f"{eid} has an unknown verdict {verdict!r}.")
            continue
        prereg = e.get("prereg")
        if not prereg or not os.path.exists(os.path.join(repo, prereg)):
            st.problems.append(f"{eid} has no pre-registration file.")
            continue
        if verdict is None:
            st.open.append(eid)
            continue
        in_current = e.get("programme", ids_p[0]) == current["id"]
        if kind == "audit":
            if verdict == "FAIL":
                st.demoted.append(f"{e.get('audits', '?')} ({eid})")
        elif in_current:
            st.spent += 1
            # A measurement passing (E04: fills land at the quote) says the tools are right,
            # not that an edge exists. Only strategy passes can defuse the stop rule.
            if kind == "measurement":
                st.measured.append(eid)
            elif verdict == "PASS":
                st.passed.append(eid)
        result = e.get("result")
        if not result or not os.path.exists(os.path.join(repo, result)):
            st.problems.append(f"{eid} has a verdict but no result file.")
            continue
        if check_git:
            # The point of pre-registration: the plan exists before the answer does.
            t_pre, t_res = _first_commit_ts(prereg, repo), _first_commit_ts(result, repo)
            if t_pre is None:
                st.problems.append(f"{eid}'s pre-registration was never committed.")
            elif t_res is not None and t_res <= t_pre:
                st.problems.append(f"{eid}'s result was committed before, or with, its "
                                   f"pre-registration.")
    return st


def main() -> int:
    st = status(load())
    print(st.sentence())
    for p in st.problems[1:]:
        print("  also:", p)
    return 1 if st.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
