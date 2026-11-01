"""The hourly E16 cycle: snapshot -> resolve last hour -> predict this hour -> lock -> publish.

    python -m forecast.cycle            # run once for the current hour (idempotent)
    python -m forecast.cycle --verify   # check the ledger's hash chain

Reads the broker; never sends an order. Paper trades exist only as ledger lines.
"""
from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np
import pandas as pd

from forecast import features as F
from forecast import ledger as L
from forecast import model as M
from forecast import players as P

HISTORY_DAYS = 30
MIN_QUOTES = 5          # fewer means the broker session failed: write nothing, retry
MAX_LAG_S = 900         # a snapshot more than 15 minutes after the hour is "late", not scored


def hour_now() -> int:
    return int(time.time()) // 3600 * 3600


def universe() -> list[str]:
    import sqlite3
    with sqlite3.connect(F.MARKET_DB) as c:
        return [r[0] for r in c.execute("select distinct symbol from bars where period='D1' order by 1")]


def spread_bps(q: dict) -> float:
    mid = (q["bid"] + q["ask"]) / 2
    return (q["ask"] - q["bid"]) / mid * 1e4


def traded_last_hour(hour: int) -> set[str]:
    """Instruments whose market was open over the last hour: a bar opened at hour - 3600."""
    import sqlite3
    with sqlite3.connect(F.MARKET_DB) as c:
        return {r[0] for r in c.execute("select distinct symbol from bars where period='H1' and ts_utc=?",
                                        (float(hour - 3600),))}


def resolve(prev_preds: list[dict], quotes: dict, hour: int, traded: set[str] | None = None,
            late: bool = False) -> list[dict]:
    """Score last hour's guesses. A market that did not trade over the hour is "closed" (its
    frozen quote would read as a zero move) and a late snapshot is "late"; neither is scored."""
    out = []
    for p in prev_preds:
        q1 = quotes.get(p["symbol"])
        r = {"kind": "resolution", "hour_utc": hour, "for_hour": p["hour_utc"], "player": p["player"],
             "symbol": p["symbol"], "pred_sha": p["sha"]}
        if late or p.get("lag_s", 0) > MAX_LAG_S:
            out.append(r | {"status": "late"})
            continue
        if traded is not None and p["symbol"] not in traded:
            out.append(r | {"status": "closed"})
            continue
        if q1 is None or not q1["ask"] > q1["bid"]:
            out.append(r | {"status": "missing"})
            continue
        m0, m1 = (p["bid"] + p["ask"]) / 2, (q1["bid"] + q1["ask"]) / 2
        r |= {"status": "ok", "bid1": q1["bid"], "ask1": q1["ask"],
              "real_bps": round(math.log(m1 / m0) * 1e4, 4)}
        if p["trade"]:
            net = math.log(q1["bid"] / p["ask"]) if p["pred_bps"] > 0 else math.log(p["bid"] / q1["ask"])
            r["paper_net_bps"] = round(net * 1e4, 4)
        out.append(r)
    return out


def predictions(hour: int, quotes: dict, xgb_model, meta: dict, lag_s: float = 0.0,
                traded: set[str] | None = None) -> list[dict]:
    """Version 2: "now" is this hour's opening price, which live is the snapshot's bid (bars
    are bid prices). Only markets that traded over the last hour are predicted."""
    bars = F.load_bars(since=hour - HISTORY_DAYS * 86400)
    bars = bars[bars.ts < hour]
    live = [s for s in quotes if traded is None or s in traded]
    now = pd.DataFrame({"symbol": live, "ts": hour, "open": [quotes[s]["bid"] for s in live],
                        "close": np.nan})
    bars = pd.concat([bars, now], ignore_index=True).sort_values(["symbol", "ts"]).reset_index(drop=True)
    df = F.make_features(bars)
    rows = df[(df.ts == hour) & df.symbol.isin(live)].dropna(subset=F.FEATURES)
    if rows.empty:
        return []
    preds = P.predict_all(rows, xgb_model, meta.get("slopes", {}))
    out = []
    for player, z in preds.items():
        for (_, row), zi in zip(rows.iterrows(), z):
            q = quotes[row.symbol]
            pb = float(zi) * float(row.vol24) * 1e4
            out.append({"kind": "prediction", "hour_utc": hour, "player": player, "symbol": row.symbol,
                        "bid": q["bid"], "ask": q["ask"], "spread_bps": round(spread_bps(q), 4),
                        "pred_z": round(float(zi), 6), "pred_bps": round(pb, 4),
                        "vol24": float(row.vol24), "trade": bool(abs(pb) > spread_bps(q)),
                        "model": meta["sha256"], "version": meta.get("version"),
                        "made_utc": time.time(), "lag_s": round(lag_s, 1)})
    return out


def score(resolutions: list[dict], preds_by_sha: dict) -> list[dict]:
    rows = []
    # Only the current model version is judged (v1 was retired unjudged; its lines lack "version").
    ok = [r for r in resolutions if r["status"] == "ok"
          and preds_by_sha[r["pred_sha"]].get("version") == M.VERSION]
    for player in P.PLAYERS:
        rs = [r for r in ok if r["player"] == player]
        if not rs:
            continue
        pr = np.array([preds_by_sha[r["pred_sha"]]["pred_bps"] for r in rs])
        re = np.array([r["real_bps"] for r in rs])
        ic = float(pd.Series(pr).rank().corr(pd.Series(re).rank())) if len(rs) >= 5 else None
        moved = re != 0
        trades = [r["paper_net_bps"] for r in rs if "paper_net_bps" in r]
        rows.append({"player": player, "n_resolved": len(rs), "ic": ic,
                     "hit_rate": (float(np.mean(np.sign(pr[moved]) == np.sign(re[moved])))
                                  if moved.any() else None),
                     "paper_trades": len(trades),
                     "paper_net_bps": float(np.mean(trades)) if trades else None})
    return rows


def publish(hour: int, head: str, n: int, model_sha: str, n_preds: int, scores: list[dict]) -> None:
    from research import supabase_sink as S
    if not S.enabled():
        return
    t = pd.Timestamp(hour, unit="s", tz="UTC").isoformat()
    S._post("forecast_chain", [{"hour_utc": t, "n_lines": n, "head_sha256": head,
                                "model_sha256": model_sha, "n_predictions": n_preds}])
    S._post("forecast_scores", [{"hour_utc": t, "model_sha256": model_sha, **s} for s in scores], upsert=True)


LOCK = "data/forecast/cycle.lock"
LOCK_STALE_S = 900


def _lock() -> bool:
    """One cycle at a time across processes (the engine loop and the standalone loop)."""
    import os
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    try:
        if time.time() - os.path.getmtime(LOCK) > LOCK_STALE_S:
            os.remove(LOCK)
    except OSError:
        pass
    try:
        os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


def run(snapshot_fn=None, now_hour: int | None = None, log=print) -> dict:
    import os
    if not _lock():
        log("another cycle is running")
        return {"skipped": True}
    try:
        return _run(snapshot_fn, now_hour, log)
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


def _run(snapshot_fn=None, now_hour: int | None = None, log=print) -> dict:
    hour = now_hour if now_hour is not None else hour_now()
    existing = L.lines()
    if any(x["kind"] == "prediction" and x["hour_utc"] == hour for x in existing) or \
       any(x["kind"] == "snapshot" and x["hour_utc"] == hour for x in existing):
        log("this hour is already recorded")
        return {"skipped": True}
    if snapshot_fn is None:
        from forecast.snapshot import Snapshot
        snap = Snapshot(universe()).run()
        quotes = snap.quotes
    else:
        quotes = snapshot_fn(hour)
    lag = time.time() - hour if now_hour is None else 0.0
    if len(quotes) < MIN_QUOTES:
        log(f"only {len(quotes)} quotes: broker session failed; nothing written, will retry")
        return {"failed": True}
    late = lag > MAX_LAG_S
    prev = [x for x in existing if x["kind"] == "prediction" and x["hour_utc"] == hour - 3600]
    traded = traded_last_hour(hour)
    res = resolve(prev, quotes, hour, traded, late)
    xgb_model, meta = M.load()
    preds = [] if late else predictions(hour, quotes, xgb_model, meta, lag, traded)
    snap_line = {"kind": "snapshot", "hour_utc": hour, "n_quotes": len(quotes), "made_utc": time.time(),
                 "lag_s": round(lag, 1), "late": late}
    head, n = L.append([snap_line] + res + preds)
    scores = score(res, {p["sha"]: p for p in prev})
    try:
        publish(hour, head, n, meta["sha256"], len(preds), scores)
    except Exception as e:                              # publishing must never stop the record
        log(f"publish failed: {e}")
    summary = {"hour_utc": hour, "quotes": len(quotes), "resolved": len(res), "predictions": len(preds),
               "head": head[:12], "lines": n, "scores": scores}
    log(json.dumps(summary, default=str))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.verify:
        ok, n = L.verify()
        print(("chain OK" if ok else f"chain BROKEN at line {n}"), f"({n} lines)")
        rok, msg = verify_remote()
        print(msg)
        return 0 if ok and rok else 1
    res = run()
    return 2 if res.get("failed") else 0


def verify_remote() -> tuple[bool, str]:
    """Every fingerprint published to Supabase must equal the hash of that line of the local
    record, and the record must be at least as long as the longest published one. This catches a
    truncated or rewritten record, which the local chain alone cannot."""
    from research import supabase_sink as S
    if not S.enabled():
        return True, "published chain: not checked (no Supabase key here)"
    import requests
    from config import settings
    r = requests.get(f"{settings.SUPABASE_URL}/rest/v1/forecast_chain?select=n_lines,head_sha256&order=id",
                     headers=S._headers(write=False), timeout=30)
    r.raise_for_status()
    pub = r.json()
    local = L.lines()
    bad = [p for p in pub if p["n_lines"] > len(local) or local[p["n_lines"] - 1]["sha"] != p["head_sha256"]]
    if bad:
        return False, f"published chain DISAGREES at {len(bad)} of {len(pub)} heads (first: {bad[0]})"
    return True, f"published chain OK ({len(pub)} heads match the local record)"


if __name__ == "__main__":
    raise SystemExit(main())
