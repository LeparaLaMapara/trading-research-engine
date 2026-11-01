"""Judge the scoreboard players against their pre-registered pass rules, from the local record.

    python -m forecast.judge          # one line per player
    python -m forecast.judge --json

E16 (docs/programme/E16-forward-scoreboard-prereg.md): xgb_v2, trend, reversion, regime. Check
after 4 weeks and 400 scored hours; pass = mean hourly IC > 0 AND mean hourly paper net > 0,
each with an always-valid (mSPRT) p below a Holm-corrected 0.05 over the 4; FAIL after 12 weeks.
E17 (E17-news-reader-prereg.md): news, judged alone at 0.05; 4 weeks and 100 hours with a view.

This only reads and reports. It never changes the record and never trades.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from forecast import ledger as L
from forecast import players as P
from learning.stats import msprt_p

ALPHA = 0.05
MIN_DAYS, FAIL_DAYS = 28, 84
RULES = {p: {"experiment": "E16", "min_hours": 400} for p in P.PLAYERS} | \
        {P.NEWS: {"experiment": "E17", "min_hours": 100}}


def hourly(lines: list[dict]) -> dict[str, pd.DataFrame]:
    """Per player: one row per scored hour with its IC (5+ resolved predictions) and paper mean."""
    preds = {x["sha"]: x for x in lines if x.get("kind") == "prediction"}
    rows = []
    for r in lines:
        if r.get("kind") != "resolution" or r.get("status") != "ok":
            continue
        p = preds.get(r["pred_sha"])
        if p is None or p.get("version") != P.JUDGED.get(r["player"]):
            continue
        rows.append({"player": r["player"], "hour": r["for_hour"], "pred": p["pred_bps"],
                     "real": r["real_bps"], "net": r.get("paper_net_bps")})
    out = {}
    if not rows:
        return out
    df = pd.DataFrame(rows)
    for player, g in df.groupby("player"):
        hrs = []
        for h, gh in g.groupby("hour"):
            ic = None
            if len(gh) >= 5 and gh.pred.nunique() > 1 and gh.real.nunique() > 1:
                ic = float(gh.pred.rank().corr(gh.real.rank()))
            net = gh.net.dropna()
            hrs.append({"hour": int(h), "ic": ic, "net": float(net.mean()) if len(net) else None})
        out[player] = pd.DataFrame(hrs).sort_values("hour")
    return out


def _holm_levels(ps: dict[str, float]) -> dict[str, float]:
    """The Holm level each player's p must beat (step-down over the group)."""
    order = sorted(ps, key=lambda k: ps[k])
    m, lv, ok = len(order), {}, True
    for i, k in enumerate(order):
        lv[k] = ALPHA / (m - i)
        ok = ok and ps[k] <= lv[k]
        if not ok:
            lv[k] = 0.0          # once one fails the step-down, no later player can pass
    return lv


def judge(lines: list[dict] | None = None) -> list[dict]:
    lines = L.lines() if lines is None else lines
    h = hourly(lines)
    res = {}
    for player, rule in RULES.items():
        d = h.get(player)
        if d is None or d.empty:
            res[player] = {"player": player, **rule, "hours": 0, "days": 0, "verdict": "no scored hours yet"}
            continue
        ic = d.ic.dropna().to_numpy(float)
        net = d.net.dropna().to_numpy(float)
        days = (d.hour.max() - d.hour.min()) / 86400
        p_ic = msprt_p(ic) if len(ic) >= 2 else 1.0
        p_net = msprt_p(net) if len(net) >= 2 else 1.0
        res[player] = {"player": player, **rule, "hours": int(len(d)), "days": round(float(days), 1),
                       "ic_hours": int(len(ic)), "mean_ic": float(ic.mean()) if len(ic) else None,
                       "p_ic": round(p_ic, 5), "paper_hours": int(len(net)),
                       "mean_net_bps": float(net.mean()) if len(net) else None, "p_net": round(p_net, 5)}
    # Holm over the E16 group on the weaker of each player's two tests; E17 alone at ALPHA.
    e16 = {k: max(v.get("p_ic", 1), v.get("p_net", 1)) for k, v in res.items() if v["experiment"] == "E16"}
    levels = _holm_levels(e16) | {P.NEWS: ALPHA}
    for k, v in res.items():
        if "p_ic" not in v:
            continue
        lvl = levels.get(k, 0.0)
        passed = (v["mean_ic"] or 0) > 0 and (v["mean_net_bps"] or 0) > 0 and \
            v["p_ic"] <= lvl and v["p_net"] <= lvl
        ready = v["days"] >= MIN_DAYS and v["hours"] >= v["min_hours"]
        v["level"] = lvl
        v["verdict"] = ("PASS: rung 1 of the capital ladder" if ready and passed else
                        "FAIL: 12 weeks without a pass" if v["days"] >= FAIL_DAYS else
                        "not yet" if ready else
                        f"too early ({v['days']:.0f} of {MIN_DAYS} days, {v['hours']} of {v['min_hours']} hours)")
    return list(res.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = judge()
    if a.json:
        print(json.dumps(out, indent=1, default=str))
        return 0
    for v in out:
        ic = f"IC {v['mean_ic']:+.3f} (p {v['p_ic']:.3f})" if v.get("mean_ic") is not None else "IC -"
        net = f"paper {v['mean_net_bps']:+.2f} bps (p {v['p_net']:.3f})" if v.get("mean_net_bps") is not None else "paper -"
        print(f"{v['experiment']} {v['player']:<10} {v['hours']:>4} h  {ic}  {net}  -> {v['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
