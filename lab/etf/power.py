"""Power, size and cost gate of the E20 pass criteria, on SYNTHETIC returns only (2026-11-23).

No real return series is read: asset parameters are round, hard-coded hypotheses (SA-like
annual means and vols), so nothing about the rule on real data is computed: 0 trials.

Rule (docs/programme/E20-jse-etf-trend-prereg.md): each of k slots (1/k of capital) holds its
asset when the month-end total-return index is above its 10-month simple average of month-end
values (Faber 2013 update, SSRN 962461), else the cash leg. Benchmark: 1/k buy-and-hold. Both
books rebalance monthly; cost is charged on traded notional.
Criteria (each a fraction of synthetic paths meeting it):
  C1 maxDD(rule) <= 0.7 x maxDD(B&H)                  (Fable spec, 2026-11-19)
  C2 Sharpe(rule) >= Sharpe(B&H) - 0.1                (annualised, excess over the cash leg)
  C3 maxDD(rule) <= 0.85 x maxDD(exposure-matched mix) (B&H x f + cash x (1-f))
  U1 Ulcer index(rule) <= 0.7 x Ulcer(B&H)            (RMS drawdown depth: uses every month)
Worlds: 'null' iid normal (nothing to time); 'null_fat' Student-t (df 4) with GARCH(1,1)-like
volatility clustering, no trend; 'alt' common bull/bear Markov regime on the equity-like assets
(bear ~20% of months, mean duration 8 months, bear mean shift -2.5%/month); 'alt_mild' -1.5%.
Gate (charter rule 5): gross = no trading cost and cash at 7%; cost = the Sharpe the venue takes
(trading plus cash drag); gate_ratio = median gross Sharpe gain / that cost, must be >= 3.
Cash legs: 'mmf' a money-market fund earning cash - 0.3%/yr, both legs traded on a switch;
'acct' account cash earning cash - 2%/yr (UNVERIFIED rate), only the asset leg traded.

    PYTHONPATH=. nice python lab/etf/power.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

SEED = 20261123
PATHS = 4000
CASH = 0.07                  # SA 3m interbank, round (hypothesis)
BROKER_SIDE = 0.0038         # EasyEquities 0.25% + 0.0795% + 0.00031%, x1.15 VAT (VENUES.md)
HALF_SPREAD = 0.0025         # UNVERIFIED (agenda 2b); 0.005 as stress
ASSETS4 = {"sa_eq": (0.11, 0.15, 1), "gl_eq": (0.11, 0.14, 1), "prop": (0.10, 0.18, 1),
           "gold": (0.09, 0.17, 0)}   # (annual mean, annual vol, follows the equity regime)
CORR_EQ = 0.6
P_BEAR_STAY = 7 / 8
P_BULL_STAY = 1 - (1 / 8) * 0.2 / 0.8


def simulate(months, world, rng, bear_shift=-0.025):
    a = ASSETS4
    k = len(a)
    mu = np.array([v[0] for v in a.values()]) / 12
    sd = np.array([v[1] for v in a.values()]) / np.sqrt(12)
    reg = np.array([v[2] for v in a.values()], dtype=bool)
    c = np.where(np.outer(reg, reg), CORR_EQ, 0.0)
    np.fill_diagonal(c, 1.0)
    L = np.linalg.cholesky(c)
    if world == "null_fat":
        df = 4
        z = rng.standard_t(df, (PATHS, months, k)) / np.sqrt(df / (df - 2))
        z = z @ L.T
        h = np.ones((PATHS, k))
        out = np.empty_like(z)
        for t in range(months):  # GARCH(1,1) on the unit variance: persistence 0.95
            out[:, t] = np.sqrt(h) * z[:, t]
            h = 0.05 + 0.10 * out[:, t] ** 2 + 0.85 * h
        return mu + sd * out
    z = rng.standard_normal((PATHS, months, k)) @ L.T
    r = mu + sd * z
    if world.startswith("alt"):
        bs = bear_shift if world == "alt" else -0.015
        bear = np.zeros((PATHS, months), dtype=bool)
        bear[:, 0] = rng.random(PATHS) < 0.2
        u = rng.random((PATHS, months))
        for t in range(1, months):
            stay = np.where(bear[:, t - 1], P_BEAR_STAY, P_BULL_STAY)
            bear[:, t] = np.where(u[:, t] < stay, bear[:, t - 1], ~bear[:, t - 1])
        r = r + np.where(bear, bs, -bs * 0.2 / 0.8)[..., None] * reg
    return r


def drawdowns(x):
    eq = np.cumprod(1 + x, axis=1)
    return 1 - eq / np.maximum.accumulate(eq, axis=1)


def book(r, w, cash_m, side, cash_leg):
    """Net monthly return of k slots; w[:, t] in {0,1} is decided at the end of t-1."""
    k = r.shape[2]
    ret = (w * r + (1 - w) * cash_m).mean(axis=2)
    a_end = w * (1 + r) / k / (1 + ret)[..., None]
    c_end = (1 - w) * (1 + cash_m) / k / (1 + ret)[..., None]
    nxt = np.concatenate([w[:, 1:], w[:, -1:]], axis=1) / k
    traded = np.abs(nxt - a_end).sum(axis=2)
    if cash_leg == "mmf":
        traded = traded + np.abs((1 / k - nxt) - c_end).sum(axis=2)
    traded[:, -1] = 0
    return ret - side * traded


def run(months, world, rng, cash_leg="mmf", half_spread=HALF_SPREAD, warm=10):
    T = months + warm
    r = simulate(T, world, rng)
    cash = CASH - (0.003 if cash_leg == "mmf" else 0.02)
    cash_m = (1 + cash) ** (1 / 12) - 1
    tr = np.cumprod(1 + r, axis=1)
    sig = np.zeros_like(tr)
    for t in range(warm - 1, T):
        sig[:, t] = tr[:, t] > tr[:, t - 9:t + 1].mean(axis=1)
    w = np.zeros_like(r)
    w[:, 1:] = sig[:, :-1]
    r, w = r[:, warm:], w[:, warm:]
    side = BROKER_SIDE + half_spread
    # Sharpe against ONE common cash rate (7%), so a low-yielding cash leg shows as cost
    # (Fable red-team 2026-11-23: measuring against the leg's own rate hid the acct drag)
    ref_m = (1 + CASH) ** (1 / 12) - 1
    shp = lambda x: (x - ref_m).mean(axis=1) / (x - ref_m).std(axis=1) * np.sqrt(12)
    res = {}
    for label, s in (("gross", 0.0), ("net", side)):
        cm = ref_m if label == "gross" else cash_m   # gross: no trading cost, cash at 7%
        rule = book(r, w, cm, s, cash_leg)
        bh = book(r, np.ones_like(w), cm, s, cash_leg)
        f = w.mean(axis=(1, 2))
        mix = bh * f[:, None] + cm * (1 - f[:, None])
        dr, db, dm = drawdowns(rule), drawdowns(bh), drawdowns(mix)
        c1 = dr.max(1) <= 0.7 * db.max(1)
        c2 = shp(rule) >= shp(bh) - 0.1
        c3 = dr.max(1) <= 0.85 * dm.max(1)
        u1 = np.sqrt((dr ** 2).mean(1)) <= 0.7 * np.sqrt((db ** 2).mean(1))
        res[label] = {
            "C1": c1.mean(), "C2": c2.mean(), "C1C2": (c1 & c2).mean(), "C1C2C3": (c1 & c2 & c3).mean(),
            "U1": u1.mean(), "U1C2": (u1 & c2).mean(),
            "median_sharpe_gain": np.median(shp(rule) - shp(bh)),
            "median_ddratio": np.median(dr.max(1) / db.max(1)),
            "median_return_gap_pa": np.median((bh - rule).mean(axis=1) * 12)}
        if label == "net":
            res["cost_pa_rule_minus_bh"] = np.median(
                ((bh - rule).mean(1) * 12) - res["gross"]["median_return_gap_pa"])
    res["switches_per_asset_pa"] = np.median(np.abs(np.diff(w, axis=1)).sum(1).mean(1) / (months / 12))
    res["invested"] = np.median(w.mean(axis=(1, 2)))
    # gate: median gross Sharpe gain vs the median Sharpe the costs take away
    res["sharpe_cost"] = res["gross"]["median_sharpe_gain"] - res["net"]["median_sharpe_gain"]
    res["gate_ratio"] = (res["gross"]["median_sharpe_gain"] / res["sharpe_cost"]
                         if res["sharpe_cost"] > 0 else float("nan"))
    return res


def rnd(d):
    return {k: (rnd(v) if isinstance(v, dict) else round(float(v), 3)) for k, v in d.items()}


def main():
    rng = np.random.default_rng(SEED)
    out = {"seed": SEED, "paths": PATHS, "cash": CASH, "broker_side": BROKER_SIDE,
           "half_spread": HALF_SPREAD, "cases": {}}
    grid = [(155, w, "mmf", HALF_SPREAD) for w in ("null", "null_fat", "alt", "alt_mild")]
    grid += [(155, w, "acct", HALF_SPREAD) for w in ("null", "null_fat", "alt", "alt_mild")]
    grid += [(155, w, "mmf", 0.005) for w in ("null", "alt")]
    grid += [(155, "alt", cl, 0.0) for cl in ("mmf", "acct")]
    grid += [(45, w, "mmf", HALF_SPREAD) for w in ("null", "alt")]
    for m, w, cl, hs in grid:
        key = f"{m}m {w} cash={cl} half_spread={hs}"
        res = rnd(run(m, w, rng, cl, hs))
        out["cases"][key] = res
        n = res["net"]
        print(f"{key:44s} C1C2 {n['C1C2']:.3f} C1C2C3 {n['C1C2C3']:.3f} U1 {n['U1']:.3f} "
              f"U1C2 {n['U1C2']:.3f} | gross dSh {res['gross']['median_sharpe_gain']:+.3f} "
              f"net dSh {n['median_sharpe_gain']:+.3f} cost {res['cost_pa_rule_minus_bh']:.4f}/yr "
              f"sw {res['switches_per_asset_pa']:.2f} gate {res['gate_ratio']:.2f}")
    json.dump(out, open("docs/results/etf-power-2026-11-23.json", "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
