"""The zoo's evaluation machinery: no lookahead, identical costs, honest verdicts."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research import episodes
from zoo import panel as P
from zoo.portfolio import buffered, portfolio_returns


def _bars(n=900, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    return pd.DataFrame({"high": close * 1.005, "low": close * 0.995, "close": close}, index=idx)


def test_features_do_not_change_when_the_future_changes():
    """Rewrite every bar after day k; no feature on or before day k may move."""
    a = _bars()
    b = a.copy()
    k = 700
    b.iloc[k + 1:] *= 1.5
    fa = P._instrument_frame("EURUSD", a)
    fb = P._instrument_frame("EURUSD", b)
    cut = a.index[k]
    feats = [c for c in fa.columns if c.startswith(("mom_", "ewmac_", "brk_"))] + \
        ["volratio", "skew60", "dd250", "sigma"]
    pd.testing.assert_frame_equal(fa.loc[:cut, feats], fb.loc[:cut, feats])


def test_targets_are_the_only_forward_columns():
    f = P._instrument_frame("EURUSD", _bars())
    assert (f["fwd_ret"].shift(1).dropna() == f["ret"].loc[f["fwd_ret"].shift(1).dropna().index]).all()


def test_buffer_holds_small_moves_and_takes_big_ones():
    out = buffered(np.array([0.1, 0.2, 0.5, 0.6, 0.2, np.nan]))
    assert list(out) == [0.0, 0.0, 0.5, 0.5, 0.2, 0.2]


def test_perfect_foresight_scores_hugely_and_zero_forecast_scores_nothing():
    rows = []
    for s in ("AAA", "BBB"):
        f = P._instrument_frame(s, _bars(seed=hash(s) % 100))
        rows.append(f.reset_index().rename(columns={"index": "date"}))
    p = pd.concat(rows, ignore_index=True)
    p["asset_class"] = "fx_major"
    costs = pd.DataFrame({"cost": [0.0001, 0.0001], "fin": [0.0, 0.0]}, index=["AAA", "BBB"])
    oracle = np.sign(p["fwd_ret"]).fillna(0)
    d = portfolio_returns(p, oracle, costs)
    assert d["net"].mean() / d["net"].std() * 16 > 5
    d0 = portfolio_returns(p, pd.Series(0.0, index=p.index), costs)
    assert d0["net"].abs().sum() == 0


def test_episode_verdicts_are_a_closed_vocabulary(tmp_path):
    db = str(tmp_path / "r.db")
    with pytest.raises(ValueError):
        episodes.record("t", "q", "BAD_STRATEGY", db=db)
    i = episodes.record("t", "q", "UNDERPOWERED", evidence={"sharpe": 0.3}, db=db)
    assert episodes.load("t", db=db)[0]["episode_id"] == i
