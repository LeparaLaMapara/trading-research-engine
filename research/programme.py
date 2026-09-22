"""The research programme: a budget of pre-registered experiments and a stop rule.

The rules are in docs/programme/README.md. This module reads docs/programme/register.json,
checks it against git history, and says in plain words where the programme stands.

    python -m research.programme
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field

REGISTER = "docs/programme/register.json"
VERDICTS = {None, "PASS", "FAIL"}


@dataclass
class Status:
    budget: int
    spent: int                       # experiments with a verdict
    passed: list[str]
    open: list[str]                  # registered, no verdict yet
    problems: list[str] = field(default_factory=list)

    @property
    def stop_rule_triggered(self) -> bool:
        return self.spent >= self.budget and not self.passed

    def sentence(self) -> str:
        if self.problems:
            return "The research register has a problem: " + self.problems[0]
        if self.stop_rule_triggered:
            return (f"All {self.budget} experiments are spent and none passed. The stop rule "
                    f"applies: write down that this account has no edge worth trading.")
        s = (f"So far {self.spent} of {self.budget} experiments are done and "
             f"{len(self.passed)} passed")
        if self.open:
            s += f"; {len(self.open)} in progress ({', '.join(self.open)})"
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


def status(reg: dict, repo: str = ".", check_git: bool = True) -> Status:
    budget = int(reg.get("budget", 0))
    exps = reg.get("experiments", [])
    st = Status(budget=budget, spent=0, passed=[], open=[])
    ids = [e.get("id") for e in exps]
    if len(set(ids)) != len(ids):
        st.problems.append("two experiments share an id.")
    if len(exps) > budget:
        st.problems.append(f"{len(exps)} experiments registered against a budget of {budget}.")
    for e in exps:
        eid, verdict = e.get("id"), e.get("verdict")
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
        st.spent += 1
        if verdict == "PASS":
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
                st.problems.append(f"{eid}'s result was committed before, or with, its pre-registration.")
    return st


def main() -> int:
    st = status(load())
    print(st.sentence())
    for p in st.problems[1:]:
        print("  also:", p)
    return 1 if st.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
