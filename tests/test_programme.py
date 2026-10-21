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


def _prog_reg(tmp_path, p1_done, p2=None, audits=()):
    exps = [{"id": f"E{i:02d}", "programme": "P1", "prereg": f"p{i}.md", "result": f"r{i}.json",
             "verdict": "FAIL", "trials": 1} for i in range(p1_done)]
    progs = [{"id": "P1", "budget": 3}]
    if p2 is not None:
        progs.append({"id": "P2", "budget": 3})
        exps += [{"id": "E90", "programme": "P2", "prereg": "p90.md", "result": "r90.json",
                  "verdict": p2, "trials": 2}]
    exps += list(audits)
    reg = _reg(tmp_path, exps)
    reg.update(programmes=progs, n_before_programme=100)
    return reg


def test_a_new_programme_needs_the_last_one_spent(tmp_path):
    st = P.status(_prog_reg(tmp_path, 2, p2="FAIL"), repo=str(tmp_path), check_git=False)
    assert any("was not spent" in p for p in st.problems)


def test_n_carries_across_programmes_and_slots_do_not(tmp_path):
    st = P.status(_prog_reg(tmp_path, 3, p2="PASS"), repo=str(tmp_path), check_git=False)
    assert not st.problems, st.problems
    assert st.programme == "P2" and st.spent == 1 and st.passed == ["E90"]
    assert st.n_tried == 100 + 3 + 2          # every trial ever, not just this programme's


def test_audits_spend_no_slot_add_no_n_and_can_demote(tmp_path):
    audit = {"id": "A01", "kind": "audit", "audits": "E07", "programme": "P1",
             "prereg": "pa.md", "result": "ra.json", "verdict": "FAIL"}
    st = P.status(_prog_reg(tmp_path, 2, audits=[audit]), repo=str(tmp_path), check_git=False)
    assert not st.problems, st.problems
    assert st.spent == 2 and st.n_tried == 102 and st.demoted == ["E07 (A01)"]


def test_an_audit_may_not_add_trials(tmp_path):
    audit = {"id": "A01", "kind": "audit", "audits": "E07", "prereg": "pa.md", "trials": 3}
    st = P.status(_prog_reg(tmp_path, 1, audits=[audit]), repo=str(tmp_path), check_git=False)
    assert any("audit but adds trials" in p for p in st.problems)


def test_real_register_counts_every_declared_trial():
    # Was pinned to 306, which went stale each time an experiment was registered. N must be
    # the documented base plus every non-audit experiment's trials, recomputed independently.
    reg = P.load()
    expect = reg["n_before_programme"] + sum(
        int(e.get("trials", 0 if e.get("kind") == "measurement" else 1))
        for e in reg["experiments"] if e.get("kind", "strategy") != "audit")
    assert P.status(reg, check_git=False).n_tried == expect >= 307
