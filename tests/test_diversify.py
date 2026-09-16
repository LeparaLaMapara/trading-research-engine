"""Breadth arithmetic: how much a second, eighth, or thirty-seventh instrument is worth.

The anchor test is `test_reproduces_carvers_published_table`. Carver's numbers (0.35 for
one instrument rising to 0.70 across 37) are a published external result, so reproducing
them from this module's own formula is a real check on the formula rather than a check
that the code agrees with itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.diversify import (CARVER_RHO, CARVER_SINGLE_SHARPE, average_correlation,
                                breadth_report, correlation_matrix,
                                diversification_multiplier, portfolio_sharpe,
                                returns_frame, select_uncorrelated)


def _corr_from_rho(n: int, rho: float) -> pd.DataFrame:
    m = np.full((n, n), rho, dtype=float)
    np.fill_diagonal(m, 1.0)
    names = [f"S{i}" for i in range(n)]
    return pd.DataFrame(m, index=names, columns=names)


# ------------------------------------------------------------------ the anchor


@pytest.mark.parametrize("n,expected", [(1, 0.35), (2, 0.45), (8, 0.61), (37, 0.70)])
def test_reproduces_carvers_published_table(n, expected):
    got = portfolio_sharpe(CARVER_SINGLE_SHARPE, _corr_from_rho(n, CARVER_RHO))
    assert got == pytest.approx(expected, abs=0.01)


def test_most_of_the_benefit_arrives_by_eight():
    """The reason the target is 5-10 uncorrelated streams and not 50 indicators."""
    one = portfolio_sharpe(CARVER_SINGLE_SHARPE, _corr_from_rho(1, CARVER_RHO))
    eight = portfolio_sharpe(CARVER_SINGLE_SHARPE, _corr_from_rho(8, CARVER_RHO))
    many = portfolio_sharpe(CARVER_SINGLE_SHARPE, _corr_from_rho(37, CARVER_RHO))
    assert (eight - one) > 3 * (many - eight)


# ------------------------------------------------------------------ the multiplier


def test_independent_streams_give_the_square_root_of_n():
    assert diversification_multiplier(_corr_from_rho(9, 0.0)) == pytest.approx(3.0, abs=1e-9)


def test_perfectly_correlated_streams_give_no_benefit():
    assert diversification_multiplier(_corr_from_rho(8, 1.0)) == pytest.approx(1.0, abs=1e-6)


def test_the_multiplier_falls_as_correlation_rises():
    prev = np.inf
    for rho in (0.0, 0.2, 0.5, 0.9):
        idm = diversification_multiplier(_corr_from_rho(8, rho))
        assert idm < prev
        prev = idm


def test_a_single_instrument_has_a_multiplier_of_one():
    assert diversification_multiplier(_corr_from_rho(1, 0.0)) == 1.0


def test_the_multiplier_never_reports_a_penalty():
    """Short history can produce a degenerate estimate. It must not read as worse than one."""
    assert diversification_multiplier(_corr_from_rho(4, -0.4)) >= 1.0


def test_average_correlation_ignores_the_diagonal():
    assert average_correlation(_corr_from_rho(5, 0.3)) == pytest.approx(0.3, abs=1e-9)


# ------------------------------------------------------------------ selection


def test_selection_prefers_the_least_correlated():
    names = ["A", "B", "C", "D"]
    m = pd.DataFrame(np.array([
        [1.00, 0.95, 0.95, 0.05],
        [0.95, 1.00, 0.95, 0.10],
        [0.95, 0.95, 1.00, 0.12],
        [0.05, 0.10, 0.12, 1.00],
    ]), index=names, columns=names)
    picked = select_uncorrelated(m, 2)
    assert set(picked) == {"A", "D"}


def test_a_strong_negative_correlation_is_not_diversification():
    """-0.95 is a shared risk factor with a sign. Treating it as independent is an error."""
    names = ["A", "B", "C"]
    m = pd.DataFrame(np.array([
        [1.00, -0.95, 0.30],
        [-0.95, 1.00, 0.25],
        [0.30, 0.25, 1.00],
    ]), index=names, columns=names)
    assert set(select_uncorrelated(m, 2)) != {"A", "B"}


def test_selection_is_bounded_by_what_exists():
    m = _corr_from_rho(3, 0.2)
    assert len(select_uncorrelated(m, 99)) == 3
    assert select_uncorrelated(m, 0) == []


# ------------------------------------------------------------------ returns alignment


def test_returns_frame_intersects_timestamps_rather_than_filling():
    """Forward-filling a closed market into an open one invents a correlation."""
    a = pd.DataFrame({"ts_utc": [1.0, 2.0, 3.0, 4.0], "close": [1.0, 1.1, 1.2, 1.3]})
    b = pd.DataFrame({"ts_utc": [2.0, 3.0], "close": [5.0, 5.5]})
    rf = returns_frame({"A": a, "B": b})
    assert list(rf.columns) == ["A", "B"]
    assert len(rf) == 1          # ts 2 loses its pct_change base for B; only ts 3 survives


def test_returns_frame_survives_an_empty_symbol():
    a = pd.DataFrame({"ts_utc": [1.0, 2.0, 3.0], "close": [1.0, 1.1, 1.2]})
    rf = returns_frame({"A": a, "B": pd.DataFrame()})
    assert list(rf.columns) == ["A"]


def test_correlation_of_identical_series_is_one():
    a = pd.DataFrame({"ts_utc": [1.0, 2.0, 3.0, 4.0], "close": [1.0, 1.1, 1.05, 1.2]})
    c = correlation_matrix(returns_frame({"A": a, "B": a.copy()}))
    assert c.loc["A", "B"] == pytest.approx(1.0, abs=1e-9)


# ------------------------------------------------------------------ the report


def test_breadth_report_table_grows_monotonically_in_size():
    r = breadth_report(_corr_from_rho(6, 0.2))
    assert [row["n"] for row in r.table] == [1, 2, 3, 4, 5, 6]
    assert r.table[-1]["sharpe"] > r.table[0]["sharpe"]
    assert r.idm > 1.0


def test_breadth_report_names_every_instrument_once():
    r = breadth_report(_corr_from_rho(5, 0.2))
    assert sorted(r.order) == sorted(_corr_from_rho(5, 0.2).columns)


# ------------------------------------------------------------------ selection bias


def _independent_returns(n_obs=2000, n_sym=12, seed=7):
    rng = np.random.default_rng(seed)
    data = rng.normal(0, 0.01, size=(n_obs, n_sym))
    return pd.DataFrame(data, columns=[f"S{i}" for i in range(n_sym)])


def test_selecting_on_noise_beats_picking_at_random():
    """Truly independent streams, so any apparent advantage is estimation noise.

    The selector still finds a 'better' basket than an arbitrary one, which is the whole
    problem: it is choosing the pairs whose sampling error happened to point down. Stated
    as a comparison against a random subset because that is the property that always
    holds. Whether the inflated number also clears sqrt(k) depends on how many candidates
    the search had to pick from: with 24 instruments and 11,925 bars the real universe
    reported 2.93 against sqrt(8) = 2.83, but 12 candidates is not enough to guarantee it.
    """
    from research.diversify import effective_corr
    rets = _independent_returns()
    corr = effective_corr(correlation_matrix(rets))
    picked = select_uncorrelated(corr, 6)
    chosen_idm = diversification_multiplier(corr.loc[picked, picked])
    arbitrary = list(corr.columns[:6])
    assert chosen_idm > diversification_multiplier(corr.loc[arbitrary, arbitrary])


def test_an_in_sample_multiplier_above_the_independent_case_is_impossible():
    """sqrt(k) is the ceiling for genuinely uncorrelated streams. Above it means noise.

    Locks the reference value the breadth script warns against, so the warning cannot
    silently start comparing to the wrong number.
    """
    assert diversification_multiplier(_corr_from_rho(8, 0.0)) == pytest.approx(np.sqrt(8))
    assert diversification_multiplier(_corr_from_rho(8, 0.01)) < np.sqrt(8)


def test_out_of_sample_idm_removes_the_inflation():
    from research.diversify import out_of_sample_idm
    r = out_of_sample_idm(_independent_returns(), k=6)
    assert r["evaluable"] is True
    assert r["in_sample_idm"] > r["out_of_sample_idm"]
    assert r["selection_bias"] > 0
    # Out of sample the basket should land on the noise floor, NOT on sqrt(k): these
    # streams are independent, so there was never any diversification to find.
    assert r["out_of_sample_idm"] == pytest.approx(r["noise_floor_idm"], abs=0.1)
    assert r["out_of_sample_idm"] < np.sqrt(6)


def test_out_of_sample_idm_refuses_on_short_history():
    from research.diversify import out_of_sample_idm
    r = out_of_sample_idm(_independent_returns(n_obs=50), k=3)
    assert r["evaluable"] is False
    assert "need 100" in r["why_not"]


def test_out_of_sample_idm_refuses_on_one_instrument():
    from research.diversify import out_of_sample_idm
    r = out_of_sample_idm(_independent_returns(n_sym=1), k=1)
    assert r["evaluable"] is False


def test_the_noise_floor_sits_below_the_textbook_square_root():
    """sqrt(k) is unreachable under the absolute-correlation convention on finite data."""
    from research.diversify import noise_floor_idm
    for n_obs in (250, 1000, 10000):
        assert noise_floor_idm(8, n_obs) < np.sqrt(8)


def test_the_noise_floor_rises_towards_the_square_root_with_more_data():
    from research.diversify import noise_floor_idm
    assert noise_floor_idm(8, 100) < noise_floor_idm(8, 10000) < np.sqrt(8)


def test_independent_streams_land_on_their_own_noise_floor():
    """The whole point: independence is not an edge, and must not be reported as one.

    Stated as a ratio near 1.0 rather than "below the floor". Out of sample the selected
    basket scatters symmetrically ABOUT the floor, so a strict inequality here would pass
    or fail on the seed, which is the kind of test that looks like evidence and is not.
    """
    from research.diversify import out_of_sample_idm
    for seed in (11, 12, 13):
        r = out_of_sample_idm(_independent_returns(n_obs=4000, n_sym=14, seed=seed), k=6)
        assert r["evaluable"] is True
        assert r["idm_vs_floor"] == pytest.approx(1.0, abs=0.06)
