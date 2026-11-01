"""The players on the E16 scoreboard. Each turns a row of inputs into a predicted next-hour
move in units of 24-hour volatility. All are counted trials (Holm over the players).

* xgb_v1     the pooled XGBoost blend (forecast/model.py)
* trend      ride the last 24 hours: slope x ret24
* reversion  snap back from the last hour: slope x ret1
* regime     calm market (24 h vol below 120 h vol): trend; wild market: snap-back

The simple players' one number each (the slope) is a least-squares fit on the same history the
XGBoost model trains on, so their predicted size is in the same units and the "bigger than the
spread" trade test treats every player alike.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from forecast import model as M

PLAYERS = ("xgb_v1", "trend", "reversion", "regime")


def _slope(x: pd.Series, y: pd.Series) -> float:
    d = pd.concat([x, y.clip(-M.CLIP, M.CLIP)], axis=1).dropna()
    xx = (d.iloc[:, 0] ** 2).sum()
    return float((d.iloc[:, 0] * d.iloc[:, 1]).sum() / xx) if xx > 0 else 0.0


def fit_slopes(df: pd.DataFrame) -> dict:
    calm = df["vol24"] < df["vol120"]
    return {"trend": _slope(df["ret24"], df["target"]),
            "reversion": _slope(df["ret1"], df["target"]),
            "regime_calm": _slope(df.loc[calm, "ret24"], df.loc[calm, "target"]),
            "regime_wild": _slope(df.loc[~calm, "ret1"], df.loc[~calm, "target"])}


def predict_all(rows: pd.DataFrame, xgb_model, slopes: dict) -> dict[str, np.ndarray]:
    calm = (rows["vol24"] < rows["vol120"]).to_numpy()
    return {
        "xgb_v1": M.predict(xgb_model, rows),
        "trend": slopes["trend"] * rows["ret24"].to_numpy(float),
        "reversion": slopes["reversion"] * rows["ret1"].to_numpy(float),
        "regime": np.where(calm, slopes["regime_calm"] * rows["ret24"].to_numpy(float),
                           slopes["regime_wild"] * rows["ret1"].to_numpy(float)),
    }
