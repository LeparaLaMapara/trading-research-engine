"""The latency lab measures execution honesty, so its own honesty is the thing to test."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import decay as D
from lab.replay import ResolutionError, fills_for_delay, pnl_from_fills, trade_segments

HOUR = 3600.0


def _tape(n=240, start=0.0, drift=0.0005, seed=3):
    """An hourly tape with a mild upward drift, so delay has something to eat."""
    rng = np.random.default_rng(seed)
    px = 100 * np.exp(np.cumsum(rng.normal(drift, 0.002, n)))
    return pd.DataFrame({"ts_utc": start + np.arange(n) * HOUR, "open": px, "close": px})


def _signals(tape, every=24):
    rows = tape.iloc[::every]
    return pd.DataFrame({"ts_close": rows["ts_utc"].to_numpy(),
                         "position": 1.0,
                         "decision_price": rows["open"].to_numpy()})


def test_a_delay_finer_than_the_data_is_refused_not_rounded():
    """The whole point: hourly bars must not be allowed to answer a millisecond question."""
    tape = _tape()
    with pytest.raises(ResolutionError):
        fills_for_delay(_signals(tape), tape, 0.01, "H1")


def test_zero_delay_fills_at_the_price_that_made_the_decision():
    tape = _tape()
    sig = _signals(tape)
    f = fills_for_delay(sig, tape, 0, "H1")
    assert (f["price"].to_numpy() == sig["decision_price"].to_numpy()).all()
    assert (f["effective_delay_s"] == 0).all()


def test_the_fill_is_never_in_the_past_and_the_effective_delay_is_reported():
    tape = _tape()
    sig = _signals(tape)
    f = fills_for_delay(sig, tape, 2 * HOUR, "H1")
    assert (f["filled_ts"] >= f["decided_ts"] + 2 * HOUR).all()
    assert (f["effective_delay_s"] >= 2 * HOUR).all()
    # And it prices from a LATER bar than the zero-delay case.
    f0 = fills_for_delay(sig, tape, 0, "H1")
    assert (f["filled_ts"].to_numpy()[:len(f0)] > f0["filled_ts"].to_numpy()[:len(f)]).all()


def test_delay_costs_a_trending_strategy_money():
    """On a tape that drifts up, buying later is buying worse. If this ever passes with the
    delay being free, the replay is not applying the delay at all."""
    tape = _tape(drift=0.002)
    sig = _signals(tape)
    early = pnl_from_fills(fills_for_delay(sig, tape, 0, "H1"), 0.0)["net"].sum()
    late = pnl_from_fills(fills_for_delay(sig, tape, 12 * HOUR, "H1"), 0.0)["net"].sum()
    assert late < early


def test_costs_are_charged_on_turnover_not_on_time():
    tape = _tape()
    sig = _signals(tape)
    sig["position"] = [1.0, -1.0] * (len(sig) // 2) + [1.0] * (len(sig) % 2)
    fills = fills_for_delay(sig, tape, 0, "H1")
    free = pnl_from_fills(fills, 0.0)["net"].sum()
    dear = pnl_from_fills(fills, 0.001)["net"].sum()
    assert dear < free


def test_trade_segments_split_on_position_change():
    pnl = pd.DataFrame({"position": [1, 1, 0, -1, -1], "net": [0.1, 0.1, 5.0, -0.2, -0.2]})
    assert trade_segments(pnl) == pytest.approx([0.2, -0.4])


def test_a_curve_that_is_negative_everywhere_has_no_threshold():
    curve = pd.DataFrame({"effective_delay_s": [0, HOUR, 2 * HOUR], "sharpe": [-0.1, -0.2, -0.3],
                          "skipped": ["", "", ""]})
    assert D.survival_threshold(curve) == (None, None, False)
    ok, why = D.feasible_from_here(None)
    assert ok is False and "not the problem" in why


def test_threshold_and_safety_margin():
    curve = pd.DataFrame({"effective_delay_s": [0, HOUR, 4 * HOUR, 12 * HOUR],
                          "sharpe": [0.5, 0.4, 0.1, -0.2], "skipped": [""] * 4})
    thr, target, censored = D.survival_threshold(curve)
    assert thr == 4 * HOUR
    assert target == 4 * HOUR * D.SAFETY_FACTOR       # never operate at the edge
    assert censored is False                          # the curve did cross inside the range


def test_a_threshold_at_the_last_bucket_is_flagged_as_censored():
    """Reporting the edge of the ruler as the edge of the strategy is the error this catches."""
    curve = pd.DataFrame({"effective_delay_s": [0, HOUR, 4 * HOUR],
                          "sharpe": [0.5, 0.4, 0.3], "skipped": [""] * 3})
    thr, _, censored = D.survival_threshold(curve)
    assert thr == 4 * HOUR and censored is True


def test_a_sub_second_edge_is_infeasible_from_this_machine():
    """Measured order path is ~0.9s typical, so a 0.5s edge cannot be run from here."""
    ok, why = D.feasible_from_here(0.5)
    assert ok is False and "INFRASTRUCTURE_INFEASIBLE" in why
    assert D.regime_for(0.5) == "sub_second"
    assert D.regime_for(12 * HOUR) == "multi_hour"


def test_regimes_come_from_seconds_not_from_names():
    assert D.regime_for(0.0005) == "ultra_low_latency"
    assert D.regime_for(30) == "seconds"
    assert D.regime_for(1800) == "minutes"


def test_a_crossing_is_reported_as_an_interval_not_a_point():
    """Section 15 of the brief, and a defect in the first version: 12h positive and 24h
    negative means the crossing is SOMEWHERE BETWEEN, which is what must be reported."""
    curve = pd.DataFrame({"effective_delay_s": [0, 12 * HOUR, 24 * HOUR],
                          "sharpe": [0.2, 0.1, -0.1], "skipped": [""] * 3})
    b = D.crossing_bracket(curve)
    assert b["status"] == "bracketed"
    assert (b["lo"], b["hi"]) == (12 * HOUR, 24 * HOUR)


def test_positive_everywhere_is_censored_not_a_threshold():
    curve = pd.DataFrame({"effective_delay_s": [0, HOUR, 4 * HOUR],
                          "sharpe": [0.5, 0.4, 0.3], "skipped": [""] * 3})
    assert D.crossing_bracket(curve)["status"] == "censored_right"


def test_negative_everywhere_is_no_edge():
    curve = pd.DataFrame({"effective_delay_s": [0, HOUR], "sharpe": [-0.1, -0.2],
                          "skipped": ["", ""]})
    assert D.crossing_bracket(curve)["status"] == "no_edge"


def test_refinement_narrows_the_bracket_and_stops_at_the_data_resolution():
    """A drifting tape makes late entries worse, so a crossing exists to be narrowed."""
    tape = _tape(n=2000, drift=0.0015)
    sig = _signals(tape, every=24)
    coarse = D.decay_curve(sig, tape, [0, 6 * HOUR, 48 * HOUR], 0.0005, 0.0, "H1", 260.0)
    b = D.crossing_bracket(coarse)
    if b["status"] != "bracketed":
        pytest.skip("synthetic tape produced no crossing; nothing to refine")
    extra, refined = D.refine_bracket(sig, tape, b, 0.0005, 0.0, "H1", 260.0, rounds=3)
    assert refined["hi"] - refined["lo"] <= b["hi"] - b["lo"]
    assert refined["lo"] >= b["lo"] and refined["hi"] <= b["hi"]
    assert refined["resolution_limit_s"] == HOUR       # never finer than the bars


def test_operating_target_uses_the_pessimistic_end():
    b = {"status": "bracketed", "lo": 8 * HOUR, "hi": 24 * HOUR}
    assert D.operating_target(b) == 8 * HOUR * D.SAFETY_FACTOR


def test_clock_correction_refuses_to_claim_precision_it_does_not_have():
    from lab.clock import corrected_latency_ms
    val, note = corrected_latency_ms(20.0, -5.0, 60.0)
    assert "BELOW CLOCK UNCERTAINTY" in note
    val, note = corrected_latency_ms(216.0, 86.0, 58.0)
    assert val == pytest.approx(302.0) and note == "ok"
