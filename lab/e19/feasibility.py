"""E19 feasibility: what capital does a whole-contract micro-futures tsmom_12m book need?

Costs and position rounding ONLY. Nothing here prints or saves a mean P&L, a Sharpe, or the mean
of (rounded minus ideal): only dispersion (correlation, tracking error, vol ratio), how often
each market can be held at all, contracts traded, and cost as a share of capital. 0 trials.

Fixed BEFORE the first run (2026-11-21), not tuned afterwards:

* Universe, fixed a priori by available micro futures with a Dukascopy proxy (pre-holdout only):
  MES US500, MNQ USTEC, MYM US30, MGC XAUUSD, SIL XAGUSD, MCL XTIUSD, M6E EURUSD, M6A AUDUSD,
  M6B GBPUSD, 10Y USTBOND. M2K dropped (no Russell 2000 proxy in the data). 2YY dropped (no
  separate short-rate series; it would duplicate the 10Y proxy).
* 10Y yield futures pay $10 per bp. Proxy: yield change = -(USTBOND return) / D with an ASSUMED
  duration D = 16, so one contract = $10 x 1e4 / 16 = $6,250 of bond-price exposure. Run with
  and without this leg.
* Ideal (fractional) book = the E19 book of zoo/portfolio.portfolio_returns scaled to money:
  equal risk per instrument, forecast f = sign(12-month momentum) (tsmom_12m), vol sigma =
  36-day EWMA of daily returns (zoo/panel.py), so
      contracts_i,t = C * (tau / 16) * IDM * f_i,t / (N * sigma_i,t * V_i,t)
  where V = dollar value of one contract per unit price return (multiplier x price),
  tau = annual vol target (headline 0.20, also 0.10), IDM = 2.0 (ASSUMED, a typical
  diversification multiplier for ~10 instruments). portfolio_returns' 0.25 forecast buffer is
  irrelevant here: f is +-1 so every change exceeds it.
* Rounded book = nearest integer contracts. Daily P&L of a book = sum c_i,t * V_i,t * fwd_ret_i,t.
* Headline: V fixed at the last pre-holdout close (today-like contract sizes; historical prices
  would make early contracts look small and flatter the answer). Secondary: historical V.
* Costs: each contract traded pays half the round trip in
  docs/results/venues-futures-costs-2026-11-20.json (fees + 1 tick; 10Y: $0.25 + $0.30 + $0.02
  per side + $1 tick = $2.14); each roll pays a full round trip on the contracts held.
  Rolls a year: equity index and FX 4, MGC 6, SIL 5, MCL 12, 10Y 12.
* Margin: exchange maintenance margins from VENUES.md (ampfutures, undated, UNVERIFIED).
* FEASIBLE at capital C (tau = 0.20, fixed V, with the 10Y leg) iff ALL of:
    (a) correlation of rounded vs ideal daily P&L >= 0.90
    (b) at least 8 of the 10 markets (7 of 9 without the 10Y) hold >= 1 contract on >= 90% of the days they have a signal
    (c) rounding trades + rolls cost <= 0.5% of capital a year
  Minimum capital = the smallest grid point that is feasible.

Window: 2004-01-01 to scripts.train_zoo.HOLDOUT_START (vault stays sealed).
Cost split (sign flips, resizing, rolls) added 2026-11-21 after the first run; cost only.
Run: PYTHONPATH=. ARTIFACT_ROOT=/mnt/t/making-money nice python lab/e19/feasibility.py
"""
import json
import os

import numpy as np
import pandas as pd

os.environ.setdefault("ARTIFACT_ROOT", "/mnt/t/making-money")
from scripts import long_history as L
from zoo.panel import build_panel

OUT = "docs/results/e19-feasibility-2026-11-21.json"
COSTS = json.load(open("docs/results/venues-futures-costs-2026-11-20.json", encoding="utf-8"))
D_BOND = 16.0
IDM = 2.0
GRID = [2_500, 5_000, 10_000, 15_000, 25_000, 50_000, 75_000, 100_000, 150_000, 250_000,
        500_000, 1_000_000]
TAUS = [0.20, 0.10]
MIN_CORR, MIN_HELD_MARKETS, MIN_HELD_SHARE, MAX_COST = 0.90, 8, 0.90, 0.005
MULT = {"MES": 5.0, "MNQ": 2.0, "MYM": 0.5, "MGC": 10.0, "SIL": 1000.0, "MCL": 100.0,
        "M6E": 12500.0, "M6A": 10000.0, "M6B": 6250.0}
ROLLS = {"MES": 4, "MNQ": 4, "MYM": 4, "MGC": 6, "SIL": 5, "MCL": 12, "M6E": 4, "M6A": 4,
         "M6B": 4, "10Y": 12}
MARGIN = {"MES": 2919, "MNQ": 4574, "MYM": 1698, "MGC": 2140, "SIL": 4325, "MCL": 930,
          "10Y": 352, "M6E": 231, "M6A": 193, "M6B": 187}
RT = {c: v["round_trip_usd"] for c, v in COSTS.items()}
RT["10Y"] = 2 * (0.25 + 0.30 + 0.02) + 1.0
PROXY = {c: v["proxy"] for c, v in COSTS.items()}
PROXY["10Y"] = "USTBOND"

paths = {k: v for k, v in L.files().items() if k in set(PROXY.values())}
p = build_panel(sorted(paths), loader=L.loader_for(paths))
p = p[(p.date >= pd.Timestamp("2004-01-01")) & (p.date < L.HOLDOUT_START)]
p = p.dropna(subset=["fwd_ret", "mom_250"])


def wide(col):
    return p.pivot(index="date", columns="symbol", values=col)


close, sig, ret, mom = wide("close"), wide("sigma"), wide("fwd_ret"), wide("mom_250")
contracts = list(PROXY)
ref = {c: float(close[PROXY[c]].dropna().iloc[-1]) for c in contracts}


def value(c, fixed):
    """Dollar value of one contract per unit price return of its proxy, by date."""
    if c == "10Y":
        return pd.Series(10.0 * 1e4 / D_BOND, index=close.index)
    px = pd.Series(ref[c], index=close.index) if fixed else close[PROXY[c]]
    return MULT[c] * px


def run(cap, tau, fixed, use, mask=None):
    n = len(use)
    ideal, rnd, vals, rets = {}, {}, {}, {}
    for c in use:
        s = PROXY[c]
        f = np.sign(mom[s])
        v = value(c, fixed)
        x = cap * (tau / 16.0) * IDM * f / (n * sig[s] * v)
        ideal[c], rnd[c], vals[c], rets[c] = x, x.round(), v, ret[s]
    I, R = pd.DataFrame(ideal), pd.DataFrame(rnd)
    V, Rt = pd.DataFrame(vals), pd.DataFrame(rets)
    if mask is not None:
        I, R, V, Rt = I[mask], R[mask], V[mask], Rt[mask]
    pi = (I * V * Rt).sum(axis=1, min_count=1).dropna()
    pr = (R * V * Rt).sum(axis=1, min_count=1).reindex(pi.index)
    years = len(pi) / 260.0
    live = I.notna()
    held = {c: round(float((R[c].abs() >= 1)[live[c]].mean()), 3) for c in use}
    traded = R.fillna(0).diff().abs().fillna(0)
    flip = np.sign(R.fillna(0)).diff().fillna(0) != 0         # trades on a sign change
    tcost = sum(float(traded[c].sum()) * RT[c] / 2 for c in use)
    fcost = sum(float(traded[c][flip[c]].sum()) * RT[c] / 2 for c in use)
    rcost = sum(float(R[c].abs().fillna(0).sum()) / 260.0 * ROLLS[c] * RT[c] for c in use)
    cost = (tcost + rcost) / years / cap
    gross = float(((R.abs() * V).sum(axis=1)).median()) / cap
    margin = float((R.abs() * pd.Series(MARGIN)[use]).sum(axis=1).median()) / cap
    sd_i = float(pi.std())
    out = {"corr": round(float(np.corrcoef(pi, pr)[0, 1]), 3) if pr.std() > 0 else 0.0,
           "te_annual_pct_cap": round(float((pr - pi).std()) * np.sqrt(260) / cap * 100, 2),
           "vol_ratio": round(float(pr.std()) / sd_i, 3) if sd_i > 0 else None,
           "ideal_vol_annual_pct": round(sd_i * np.sqrt(260) / cap * 100, 1),
           "markets_held_90pct": int(sum(h >= MIN_HELD_SHARE for h in held.values())),
           "held_share": held, "cost_pct_cap_yr": round(cost * 100, 3),
           "cost_split_pct_cap_yr": {"sign_flips": round(fcost / years / cap * 100, 3),
                                     "resizing": round((tcost - fcost) / years / cap * 100, 3),
                                     "rolls": round(rcost / years / cap * 100, 3)},
           "contracts_traded_yr": round(float(traded.sum().sum()) / years, 1),
           "median_gross_notional_x_cap": round(gross, 2),
           "median_margin_pct_cap_UNVERIFIED": round(margin * 100, 1)}
    out["feasible"] = bool(out["corr"] >= MIN_CORR
                           and out["markets_held_90pct"] >= min(MIN_HELD_MARKETS, len(use) - 2)
                           and cost <= MAX_COST)
    return out


res = {"universe": PROXY, "ref_price": ref, "idm": IDM, "bond_duration_assumed": D_BOND,
       "thresholds": {"min_corr": MIN_CORR, "min_held_markets": MIN_HELD_MARKETS,
                      "min_held_share": MIN_HELD_SHARE, "max_cost": MAX_COST},
       "window": [str(p.date.min().date()), str(p.date.max().date())],
       "min_proxy_price": {c: float(close[PROXY[c]].min()) for c in contracts if c != "10Y"},
       "runs": {}}
nobond = [c for c in contracts if c != "10Y"]
for label, fixed, use in (("fixed_V_with_10Y", True, contracts), ("fixed_V_no_10Y", True, nobond),
                          ("historical_V_with_10Y", False, contracts)):
    for tau in TAUS:
        key = f"{label}_tau{tau:.2f}"
        res["runs"][key] = {}
        for cap in GRID:
            r = run(cap, tau, fixed, use)
            res["runs"][key][cap] = r
            print(f"{key:30} ${cap:>9,} corr {r['corr']:5.2f} te {r['te_annual_pct_cap']:6.2f}% "
                  f"held {r['markets_held_90pct']:2}/{len(use)} cost {r['cost_pct_cap_yr']:6.3f}% "
                  f"notional {r['median_gross_notional_x_cap']:5.2f}x margin "
                  f"{r['median_margin_pct_cap_UNVERIFIED']:5.1f}% {'FEASIBLE' if r['feasible'] else ''}")
        feas = [c for c in GRID if res["runs"][key][c]["feasible"]]
        res["runs"][key]["min_feasible_capital"] = feas[0] if feas else None
        print(key, "minimum feasible capital:", feas[0] if feas else "none on grid")

# Era split of the historical-V run (contract sizes as they were), headline tau, correlation only.
eras = {}
for era, (a, b) in L.PERIODS.items():
    m = (close.index >= pd.Timestamp(a)) & (close.index < pd.Timestamp(b))
    eras[era] = {cap: run(cap, 0.20, False, contracts, m)["corr"] for cap in (25_000, 100_000)}
res["historical_V_corr_by_era_tau0.20"] = eras
print("historical V corr by era:", eras)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(res, fh, indent=1, default=str)
print("wrote", OUT)
