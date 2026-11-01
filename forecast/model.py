"""E16 model version 1: one XGBoost regressor pooled over all instruments.

    python -m forecast.model --train            # train on everything to date, save, print hash
    python -m forecast.model --diagnostic 2025-01-01   # train before, score after (not E16)

The saved file's SHA-256 is the model's identity; every prediction carries it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time

import numpy as np
import pandas as pd
import xgboost as xgb

from forecast import features as F

DIR = "data/forecast"
CURRENT = os.path.join(DIR, "model-current.json")
PARAMS = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
              colsample_bytree=0.8, min_child_weight=200, objective="reg:squarederror",
              tree_method="hist", random_state=16, n_jobs=4)
CLIP = 5.0


def file_sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def fit(df: pd.DataFrame) -> xgb.XGBRegressor:
    d = df.dropna(subset=F.FEATURES + ["target"])
    m = xgb.XGBRegressor(**PARAMS)
    m.fit(d[F.FEATURES].to_numpy(np.float32), d["target"].clip(-CLIP, CLIP).to_numpy(np.float32))
    return m


def save(m: xgb.XGBRegressor, cutoff_ts: int, n_rows: int, slopes: dict | None = None) -> str:
    os.makedirs(DIR, exist_ok=True)
    tmp = os.path.join(DIR, "model-tmp.json")
    m.save_model(tmp)
    sha = file_sha(tmp)
    final = os.path.join(DIR, f"model-{sha[:16]}.json")
    os.replace(tmp, final)
    with open(CURRENT, "w", encoding="utf-8") as fh:
        json.dump({"file": final, "sha256": sha, "version": "v1", "trained_to_ts": cutoff_ts,
                   "rows": n_rows, "slopes": slopes or {}, "trained": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, fh)
    return sha


def load() -> tuple[xgb.XGBRegressor, dict]:
    with open(CURRENT, encoding="utf-8") as fh:
        meta = json.load(fh)
    if file_sha(meta["file"]) != meta["sha256"]:
        raise RuntimeError("model file does not match its recorded hash")
    m = xgb.XGBRegressor()
    m.load_model(meta["file"])
    return m, meta


def predict(m: xgb.XGBRegressor, rows: pd.DataFrame) -> np.ndarray:
    return m.predict(rows[F.FEATURES].to_numpy(np.float32))


def ic_by_hour(df: pd.DataFrame, pred: np.ndarray) -> pd.Series:
    d = df.assign(pred=pred).dropna(subset=["target"])
    d = d[d.groupby("ts")["symbol"].transform("count") >= 5]
    return d.groupby("ts").apply(lambda g: g["pred"].rank().corr(g["target"].rank()), include_groups=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--diagnostic", default=None, help="train before this date, score after")
    a = ap.parse_args(argv)
    df = F.make_features(F.load_bars())
    if a.diagnostic:
        cut = int(pd.Timestamp(a.diagnostic, tz="UTC").timestamp())
        tr, te = df[df.ts < cut - 3600], df[df.ts >= cut]
        m = fit(tr)
        ic = ic_by_hour(te, predict(m, te)).dropna()
        t = ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic))
        print(json.dumps({"train_rows": int(tr.target.notna().sum()), "test_hours": int(len(ic)),
                          "mean_ic": round(float(ic.mean()), 4), "t": round(float(t), 2),
                          "share_positive": round(float((ic > 0).mean()), 3)}))
    if a.train:
        cutoff = int(df.ts.max())
        from forecast import players
        m = fit(df)
        slopes = players.fit_slopes(df)
        print("model sha256", save(m, cutoff, int(df.target.notna().sum()), slopes), slopes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
