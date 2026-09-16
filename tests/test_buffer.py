"""No-trade buffers. The properties locked here are turnover reduction and causality.

A buffer that did not reduce turnover would be pointless; a buffer that peeked at the
future would be worse than pointless, because the resulting backtest would look better
for exactly the wrong reason.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import Strategy
from strategy.buffer import (Buffered, apply_buffer, min_holding_period, turnover_of)


def _whipsaw(n=400):
    """A signal that changes its mind every single bar. Worst case for costs."""
    return pd.Series(np.where(np.arange(n) % 2 == 0, 1.0, -1.0), dtype=float)


def _noisy(n=400, seed=3):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.choice([-1.0, 0.0, 1.0], size=n), dtype=float)


# ------------------------------------------------------------------ apply_buffer


def test_a_buffer_reduces_turnover_on_a_whipsaw():
    raw = _whipsaw()
    assert turnover_of(apply_buffer(raw, 0.5)) < turnover_of(raw)


def test_a_bigger_buffer_reduces_turnover_further():
    raw = _noisy()
    t0 = turnover_of(raw)
    t_small = turnover_of(apply_buffer(raw, 0.3))
    t_big = turnover_of(apply_buffer(raw, 0.9))
    assert t_big <= t_small <= t0


def test_a_zero_buffer_changes_nothing():
    raw = _noisy()
    pd.testing.assert_series_equal(apply_buffer(raw, 0.0), raw.astype(float))


def test_the_held_position_never_overshoots_the_target():
    raw = _noisy()
    held = apply_buffer(raw, 0.4)
    assert held.abs().max() <= raw.abs().max() + 1e-12


def test_a_constant_signal_is_entered_once_and_then_left_alone():
    raw = pd.Series(np.ones(100))
    held = apply_buffer(raw, 0.5)
    # One entry to the near edge of the dead zone, then flat forever after.
    assert held.iloc[0] == 0.5
    assert (held.diff().fillna(0.0).iloc[1:] == 0).all()


def test_the_buffer_is_causal():
    """Truncating the future must not change any position already decided."""
    raw = _noisy(400)
    full = apply_buffer(raw, 0.5)
    prefix = apply_buffer(raw.iloc[:200], 0.5)
    pd.testing.assert_series_equal(full.iloc[:200], prefix)


def test_index_is_preserved():
    raw = pd.Series([1.0, -1.0, 1.0], index=[10, 20, 30])
    assert list(apply_buffer(raw, 0.5).index) == [10, 20, 30]


# ------------------------------------------------------------------ minimum holding period


def test_min_holding_period_reduces_turnover():
    raw = _whipsaw()
    assert turnover_of(min_holding_period(raw, 10)) < turnover_of(raw)


def test_min_holding_period_of_one_changes_nothing():
    raw = _noisy()
    pd.testing.assert_series_equal(min_holding_period(raw, 1), raw.astype(float))


def test_a_position_survives_the_lock_window():
    raw = pd.Series([1.0] + [0.0] * 20)
    held = min_holding_period(raw, 5)
    assert (held.iloc[:5] == 1.0).all()      # locked
    assert held.iloc[-1] == 0.0              # eventually released


def test_min_holding_period_is_causal():
    raw = _noisy(400)
    full = min_holding_period(raw, 7)
    prefix = min_holding_period(raw.iloc[:200], 7)
    pd.testing.assert_series_equal(full.iloc[:200], prefix)


# ------------------------------------------------------------------ the wrapper


class _Whip(Strategy):
    name = "whip"

    def generate_signals(self, bars):
        return _whipsaw(len(bars))

    def economic_rationale(self):
        return "changes its mind constantly"


def _bars(n=400):
    close = 1.10 + np.cumsum(np.random.default_rng(0).normal(0, 0.001, n))
    return pd.DataFrame({"ts_utc": np.arange(n) * 3600.0, "close": close})


def test_the_wrapper_reduces_turnover_end_to_end():
    bars = _bars()
    raw = _Whip().generate_signals(bars)
    wrapped = Buffered(_Whip(), buffer=0.5).generate_signals(bars)
    assert turnover_of(wrapped) < turnover_of(raw)


def test_the_wrapper_names_itself_honestly():
    assert "buf" in Buffered(_Whip(), buffer=0.5).name
    assert "hold9" in Buffered(_Whip(), buffer=0.0, min_hold_bars=9).name
    assert Buffered(_Whip(), buffer=0.0).name == "whip"


def test_the_wrapper_keeps_the_inner_rationale():
    assert "constantly" in Buffered(_Whip()).economic_rationale()


def test_both_filters_compose():
    bars = _bars()
    raw = _Whip().generate_signals(bars)
    both = Buffered(_Whip(), buffer=0.5, min_hold_bars=8).generate_signals(bars)
    assert turnover_of(both) < turnover_of(raw)
    assert len(both) == len(raw)
