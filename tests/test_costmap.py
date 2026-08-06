"""Cost-map aggregation on a fixed fixture."""
import pandas as pd

from telemetry.costmap import aggregate


def test_aggregate_medians_and_counts():
    ticks = pd.DataFrame([
        {"symbol": "EURUSD", "hour_of_week": 84, "spread_pips": 0.8},
        {"symbol": "EURUSD", "hour_of_week": 84, "spread_pips": 1.2},
        {"symbol": "EURUSD", "hour_of_week": 84, "spread_pips": 1.0},
        {"symbol": "EURUSD", "hour_of_week": 10, "spread_pips": 3.0},
        {"symbol": "USDJPY", "hour_of_week": 84, "spread_pips": 0.5},
    ])
    cm = aggregate(ticks)
    eur84 = cm[(cm.symbol == "EURUSD") & (cm.hour_of_week == 84)].iloc[0]
    assert eur84["median_spread_pips"] == 1.0
    assert eur84["tick_count"] == 3
    assert eur84["dow"] == "Thu" and eur84["hour_sast"] == 12
    # cheapest EURUSD bucket is hour_of_week 84, not 10
    assert cm[cm.symbol == "EURUSD"]["median_spread_pips"].min() == 1.0
