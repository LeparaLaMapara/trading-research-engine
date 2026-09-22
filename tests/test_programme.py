"""The research programme register: budget, pre-registration, the stop rule."""
from __future__ import annotations

from research import programme as P


def _reg(tmp_path, exps, budget=10):
    for e in exps:
        for k in ("prereg", "result"):
            if e.get(k):
                (tmp_path / e[k]).write_text("x")
    return {"budget": budget, "experiments": exps}


def test_the_real_register_is_valid():
    st = P.status(P.load(), check_git=False)
    assert not st.problems, st.problems


def test_open_experiment_is_in_progress(tmp_path):
    st = P.status(_reg(tmp_path, [{"id": "E01", "prereg": "p1.md", "verdict": None}]),
                  repo=str(tmp_path), check_git=False)
    assert st.open == ["E01"] and st.spent == 0 and not st.problems


def test_a_verdict_needs_a_result_file(tmp_path):
    st = P.status(_reg(tmp_path, [{"id": "E01", "prereg": "p1.md", "verdict": "FAIL"}]),
                  repo=str(tmp_path), check_git=False)
    assert any("no result file" in p for p in st.problems)


def test_missing_preregistration_is_a_problem(tmp_path):
    st = P.status({"budget": 10, "experiments": [{"id": "E01", "prereg": "nope.md"}]},
                  repo=str(tmp_path), check_git=False)
    assert any("no pre-registration" in p for p in st.problems)


def test_the_stop_rule_fires_when_the_budget_is_spent_without_a_pass(tmp_path):
    exps = [{"id": f"E{i}", "prereg": f"p{i}.md", "result": f"r{i}.json", "verdict": "FAIL"}
            for i in range(3)]
    st = P.status(_reg(tmp_path, exps, budget=3), repo=str(tmp_path), check_git=False)
    assert st.stop_rule_triggered and "stop rule" in st.sentence()


def test_one_pass_means_the_stop_rule_does_not_fire(tmp_path):
    exps = [{"id": f"E{i}", "prereg": f"p{i}.md", "result": f"r{i}.json",
             "verdict": "PASS" if i == 0 else "FAIL"} for i in range(3)]
    st = P.status(_reg(tmp_path, exps, budget=3), repo=str(tmp_path), check_git=False)
    assert not st.stop_rule_triggered and st.passed == ["E0"]


def test_over_budget_is_a_problem(tmp_path):
    exps = [{"id": f"E{i}", "prereg": f"p{i}.md", "verdict": None} for i in range(3)]
    st = P.status(_reg(tmp_path, exps, budget=2), repo=str(tmp_path), check_git=False)
    assert any("budget" in p for p in st.problems)


def test_a_measurement_pass_does_not_defuse_the_stop_rule(tmp_path):
    exps = [{"id": "E0", "kind": "measurement", "prereg": "p0.md", "result": "r0.json",
             "verdict": "PASS"},
            {"id": "E1", "prereg": "p1.md", "result": "r1.json", "verdict": "FAIL"}]
    st = P.status(_reg(tmp_path, exps, budget=2), repo=str(tmp_path), check_git=False)
    assert st.passed == [] and st.measured == ["E0"] and st.stop_rule_triggered
