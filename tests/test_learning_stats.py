import numpy as np

from learning import stats


def test_pbo_low_for_a_real_edge_high_for_pure_noise():
    # pure noise: the in-sample winner is a coin flip out of sample -> PBO near 0.5 on average
    # (one draw varies a lot because the splits share data)
    p_noise = np.mean([stats.pbo_cscv(np.random.default_rng(s).normal(0, 0.01, (1000, 20)),
                                      n_blocks=10)["pbo"] for s in range(20)])
    assert 0.4 < p_noise < 0.65
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 0.01, (2000, 20))
    # one column carries a steady edge -> it wins in and out of sample -> PBO near 0
    edge = noise.copy()
    edge[:, 3] += 0.004
    assert stats.pbo_cscv(edge, n_blocks=10)["pbo"] < 0.05


def test_pbo_refuses_too_little_data():
    assert stats.pbo_cscv(np.zeros((10, 1)))["pbo"] is None


def test_t_bars_follow_harvey_liu_zhu():
    assert stats.t_bar(new_family=True) == 3.0
    assert stats.t_bar(new_family=False) == 2.0


def test_msprt_is_conservative_under_the_null():
    # Always valid: peeking after every observation must not push false alarms above alpha.
    rng = np.random.default_rng(0)
    false = sum(stats.msprt_p(rng.normal(0, 1, 300)) < 0.05 for _ in range(300))
    assert false / 300 <= 0.06


def test_msprt_finds_a_clear_edge():
    rng = np.random.default_rng(2)
    assert stats.msprt_p(rng.normal(0.5, 1, 200)) < 1e-3


def test_sequential_verdicts():
    rng = np.random.default_rng(3)
    assert stats.sequential_verdict(rng.normal(0.6, 1, 150), worthwhile=0.1)["verdict"] == "IN"
    assert stats.sequential_verdict(rng.normal(-0.6, 1, 150), worthwhile=0.1)["verdict"] == "OUT"
    assert stats.sequential_verdict(rng.normal(0, 1, 5), worthwhile=0.1)["verdict"] == "OPEN"


def test_thompson_prefers_the_better_candidate_but_still_explores():
    cands = [{"id": "good", "prior_mean": 0, "prior_sd": 1, "n": 200, "mean": 0.3, "sd": 1},
             {"id": "bad", "prior_mean": 0, "prior_sd": 1, "n": 200, "mean": -0.3, "sd": 1},
             {"id": "new", "prior_mean": 0, "prior_sd": 1, "n": 0, "mean": 0, "sd": 1}]
    picks = [stats.thompson_pick(cands, 1, seed=s)[0] for s in range(400)]
    assert picks.count("good") > picks.count("bad")
    assert picks.count("new") > 0


def test_ruin_probability_grows_with_risk():
    r = [-1.0, -1.0, 1.5, -1.0, 2.0]
    low = stats.ruin_probability(r, risk_usd=1.0, equity=80, floor=20, max_drawdown=0.4)["p_ruin"]
    high = stats.ruin_probability(r, risk_usd=10.0, equity=80, floor=20, max_drawdown=0.4)["p_ruin"]
    assert 0 <= low < high <= 1


def test_sharpe_upper_bound_above_point_estimate():
    rng = np.random.default_rng(4)
    r = rng.normal(0.0005, 0.01, 2500)
    assert stats.sharpe_upper_bound(r, 252) > stats.annual_sharpe(r, 252)
