"""E10: the family screen. Every evidence family, across the instruments the broker offers.

Pre-registered in docs/programme/E10-family-screen-prereg.md, which fixes everything below
before any result exists. One honest method for all:

  * Data: D1 bars in data/market.db from 2015-01-01 to END (H1 for time of day), the 60
    instruments with the longest D1 history at this broker.
  * Costs: measured round-trip spread (backtest.run.measured_cost) plus commission both
    sides, on every change of position; the broker's financing FEE (zoo.financing) on every
    held bar, both directions; for currency pairs the rate DIFFERENTIAL from point-in-time
    3-month rates (2-month publication lag), earned or paid by direction.
  * Every variant x instrument is one trial and is added to the running N.
  * Per trial: t-statistic of daily net returns, annual net Sharpe and its 95% upper bound,
    net Sharpe at doubled costs, deflated Sharpe at the running N. Per family: PBO by CSCV
    over all its trials.

Verdict per trial (the screen; never a live licence):
  IN       t >= the Harvey-Liu-Zhu bar (2.0 for a published family, 3.0 for a new one),
           family PBO < 0.5, deflated Sharpe at N >= 0.5, net Sharpe at double costs > 0.
           -> a forward-test candidate.
  OUT      the 95% upper bound of the annual net Sharpe is below 0.3 (the smallest Sharpe
           that serves the family goal in three years): ruled out at this broker's costs.
  UNDECIDED otherwise.

    python -m learning.screen --out docs/results/E10-family-screen.json --record
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

from backtest.run import measured_cost
from backtest.walkforward import deflated_sharpe_ratio
from config import settings
from learning import families as F
from learning import stats
from zoo import financing as FIN

START, END = "2015-01-01", "2026-09-15"
MAX_INSTRUMENTS = 60
MIN_D1_BARS = 750
COMMISSION_SIDE = 0.000035
SHARPE_WORTHWHILE = 0.3
DSR_SCREEN = 0.5
PBO_MAX = 0.5
#: Index and other currencies in the 3-month rate files (scripts/carry.py's source).
RATE_CC = {"USD": "US", "EUR": "EZ", "GBP": "GB", "JPY": "JP", "AUD": "AU", "NZD": "NZ",
           "CAD": "CA", "CHF": "CH", "NOK": "NO", "SEK": "SE", "PLN": "PL", "MXN": "MX",
           "ZAR": "ZA", "SGD": "SG"}
RATES_DIR = os.environ.get("RATES_DIR", os.path.join(settings.ARTIFACT_ROOT, "features", "rates"))
PUBLICATION_LAG_MONTHS = 2
USD_FOREIGN = {"EURUSD": "EUR", "GBPUSD": "GBP", "AUDUSD": "AUD", "NZDUSD": "NZD"}
USD_BASE = {"USDCAD": "CAD", "USDCHF": "CHF", "USDJPY": "JPY", "USDMXN": "MXN", "USDNOK": "NOK",
            "USDPLN": "PLN", "USDSEK": "SEK", "USDSGD": "SGD", "USDZAR": "ZAR"}
H1_USD_PAIRS = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "USDCHF")


def market_db() -> str:
    return os.environ.get("MARKET_DB", "data/market.db")


def is_crypto(sym: str) -> bool:
    return sym.endswith("USD") and sym[:-3] in {"BTC", "ETH", "LTC", "BCH", "XRP", "ADA", "SOL", "DOT"}


def is_fx(sym: str) -> bool:
    return len(sym) == 6 and sym[:3] in RATE_CC and sym[3:] in RATE_CC


def bars_per_year(sym: str) -> float:
    return 365.0 if is_crypto(sym) else 260.0


def trade_date(ts_utc: pd.Series) -> pd.DatetimeIndex:
    """A D1 bar opens at 21:00 or 22:00 UTC the evening before its trading day."""
    return pd.DatetimeIndex(pd.to_datetime(ts_utc + 6 * 3600, unit="s").dt.normalize())


def universe(conn: sqlite3.Connection, swaps: dict) -> list[str]:
    rows = conn.execute(
        "SELECT symbol, COUNT(*) FROM bars WHERE period='D1' AND ts_utc < ? GROUP BY symbol",
        (pd.Timestamp(END, tz="UTC").timestamp(),)).fetchall()
    ok = sorted([(n, s) for s, n in rows if n >= MIN_D1_BARS and s in swaps], reverse=True)
    return sorted(s for _, s in ok[:MAX_INSTRUMENTS])


def load_d1(conn: sqlite3.Connection, sym: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT ts_utc, close FROM bars WHERE symbol=? AND period='D1' AND ts_utc>=? AND ts_utc<? "
        "ORDER BY ts_utc", conn, params=(sym, pd.Timestamp(START, tz="UTC").timestamp() - 400 * 86400,
                                         pd.Timestamp(END, tz="UTC").timestamp()))
    df.index = trade_date(df["ts_utc"])
    return df[~df.index.duplicated(keep="last")]


def load_rates() -> pd.DataFrame:
    cols = {}
    for ccy, cc in RATE_CC.items():
        path = os.path.join(RATES_DIR, f"IR3TIB01{cc}M156N.csv")
        if not os.path.exists(path):
            continue
        try:
            s = pd.read_csv(path)
            s.columns = ["month", "rate"]
        except (ValueError, pd.errors.ParserError):
            continue                     # e.g. the SGD file is an HTML error page, not data
        s["rate"] = pd.to_numeric(s["rate"], errors="coerce")
        s = s.dropna()
        s["usable"] = pd.to_datetime(s["month"]) + pd.DateOffset(months=PUBLICATION_LAG_MONTHS)
        cols[ccy] = s.set_index("usable")["rate"]
    if not cols:
        return pd.DataFrame()
    df = pd.DataFrame(cols).sort_index()
    days = pd.date_range(df.index.min(), pd.Timestamp(END), freq="D")
    return df.reindex(days).ffill()


def differential(sym: str, dates: pd.DatetimeIndex, rates: pd.DataFrame) -> pd.Series | None:
    """Annual % (base rate minus quote rate), point in time; None if not covered."""
    if not is_fx(sym) or rates.empty or sym[:3] not in rates or sym[3:] not in rates:
        return None
    d = (rates[sym[:3]] - rates[sym[3:]]).reindex(dates)
    return d if d.notna().mean() > 0.8 else None


def instrument_costs(sym: str, ref: float, swaps: dict) -> dict:
    cm = measured_cost(sym, ref_price=ref)
    cost_rt = cm.spread_pips * cm.pip_size / ref + 2 * COMMISSION_SIDE
    fee, _ = FIN.fee_and_differential(swaps[sym], ref)
    return {"cost_rt": float(cost_rt), "fee": float(fee)}


def net_returns(pos: pd.Series, ret: pd.Series, cost_rt: float, fee: float, bpy: float,
                diff_pct: pd.Series | None, cost_mult: float = 1.0) -> pd.Series:
    """Daily net return of holding `pos` (point in time) through bar returns `ret`."""
    turnover = pos.diff().abs().fillna(pos.abs())
    fin = pos.abs() * fee / bpy
    if diff_pct is not None:
        fin = fin - pos * diff_pct.fillna(0.0) / 100.0 / bpy
    return pos * ret - turnover * cost_rt * cost_mult / 2.0 - fin


def evaluate(r: pd.Series, r_double: pd.Series, bpy: float) -> dict:
    r = r[r.index >= pd.Timestamp(START)]
    r_double = r_double[r_double.index >= pd.Timestamp(START)]
    sd = r.std(ddof=1)
    return {"n": int(len(r)), "t": round(stats.t_stat(r), 3),
            "sharpe": round(stats.annual_sharpe(r, bpy), 3),
            "sharpe_upper95": round(stats.sharpe_upper_bound(r, bpy), 3),
            "sharpe_double_costs": round(stats.annual_sharpe(r_double, bpy), 3),
            "per_obs_sharpe": float(r.mean() / sd) if sd > 0 else 0.0,
            "mean": float(r.mean()), "sd": float(sd) if sd > 0 else 0.0,
            "years": round(len(r) / bpy, 1)}


def screen(record: bool = False, n_prior: int | None = None, log=print) -> dict:
    t0 = time.time()
    swaps = FIN.load(settings.SWAPS_JSON)
    rates = load_rates()
    trials: list[dict] = []
    series: dict[str, pd.Series] = {}                # trial id -> daily net returns
    with sqlite3.connect(f"file:{market_db()}?mode=ro", uri=True) as conn:
        syms = universe(conn, swaps)
        log(f"universe: {len(syms)} instruments")
        fx_closes: dict[str, pd.Series] = {}
        for sym in syms:
            bars = load_d1(conn, sym)
            close = bars["close"]
            ret = close.pct_change().fillna(0.0)
            bpy = bars_per_year(sym)
            c = instrument_costs(sym, float(close.iloc[-1]), swaps)
            diff = differential(sym, close.index, rates)
            if sym in USD_FOREIGN:
                fx_closes[USD_FOREIGN[sym]] = close
            elif sym in USD_BASE:
                fx_closes[USD_BASE[sym]] = 1.0 / close
            for fam, var, params in F.VARIANTS:
                if fam == "time_of_day":
                    continue
                if fam in ("tsmom", "reversal"):
                    pos = getattr(F, fam)(close, params["lookback"])
                elif fam == "turn_month":
                    pos = F.turn_month(close.index, params["before"], params["after"])
                elif fam == "carry":
                    if diff is None:
                        continue
                    pos = F.carry(close.index, diff, params["min_diff_pct"])
                else:
                    continue
                r = net_returns(pos, ret, c["cost_rt"], c["fee"], bpy, diff)
                r2 = net_returns(pos, ret, c["cost_rt"], c["fee"], bpy, diff, cost_mult=2.0)
                tid = f"{var}:{sym}"
                m = evaluate(r, r2, bpy)
                trials.append({"id": tid, "family": fam, "variant": var, "params": params,
                               "symbol": sym, "period": "D1", "bars_per_year": bpy,
                               "cost_rt_bps": round(c["cost_rt"] * 1e4, 2),
                               "fee_annual": round(c["fee"], 5), "carry_from_rates": diff is not None,
                               **m})
                series[tid] = r[r.index >= pd.Timestamp(START)].astype("float32")
        # Time of day on H1.
        for sym in [s for s in H1_USD_PAIRS if s in syms]:
            df = pd.read_sql_query(
                "SELECT ts_utc, close FROM bars WHERE symbol=? AND period='H1' AND ts_utc>=? "
                "AND ts_utc<? ORDER BY ts_utc", conn,
                params=(sym, pd.Timestamp(START, tz="UTC").timestamp(),
                        pd.Timestamp(END, tz="UTC").timestamp()))
            if len(df) < 5000:
                continue
            idx = pd.DatetimeIndex(pd.to_datetime(df["ts_utc"], unit="s"))
            close = pd.Series(df["close"].to_numpy(), index=idx)
            ret = close.pct_change().fillna(0.0)
            c = instrument_costs(sym, float(close.iloc[-1]), swaps)
            hours_per_year = len(close) / max((idx[-1] - idx[0]).days / 365.25, 1e-9)
            for fam, var, params in F.VARIANTS:
                if fam != "time_of_day":
                    continue
                pos = F.time_of_day(idx, sym.endswith("USD"), params["start_utc"], params["end_utc"])
                # financing: the window closes before the 21:00 UTC rollover, so no swap is paid
                r_h = net_returns(pos, ret, c["cost_rt"], 0.0, hours_per_year, None)
                r2_h = net_returns(pos, ret, c["cost_rt"], 0.0, hours_per_year, None, 2.0)
                r = r_h.groupby(r_h.index.normalize()).sum()
                r2 = r2_h.groupby(r2_h.index.normalize()).sum()
                tid = f"{var}:{sym}"
                m = evaluate(r, r2, 260.0)
                trials.append({"id": tid, "family": fam, "variant": var, "params": params,
                               "symbol": sym, "period": "H1", "bars_per_year": 260.0,
                               "cost_rt_bps": round(c["cost_rt"] * 1e4, 2), "fee_annual": 0.0,
                               "carry_from_rates": False, **m})
                series[tid] = r.astype("float32")
            del df, close, ret
            gc.collect()
    # Currency cross-sectional momentum: one portfolio per variant.
    closes = pd.DataFrame(fx_closes).sort_index().ffill()
    closes = closes[closes.index.dayofweek < 5]
    rets = closes.pct_change().fillna(0.0)
    leg_cost = {}
    for ccy in closes.columns:
        pair = next(p for p, c_ in {**USD_FOREIGN, **USD_BASE}.items() if c_ == ccy)
        leg_cost[ccy] = instrument_costs(pair, float(fx_closes[ccy].iloc[-1]) if pair in USD_FOREIGN
                                         else 1.0 / float(fx_closes[ccy].iloc[-1]), swaps)
    for fam, var, params in F.PORTFOLIO_VARIANTS:
        w = F.xs_momentum(closes, params["lookback"], params["top"])
        legs = []
        for ccy in closes.columns:
            d = None
            if not rates.empty and ccy in rates and "USD" in rates:
                d = (rates[ccy] - rates["USD"]).reindex(closes.index)
            legs.append(net_returns(w[ccy], rets[ccy], leg_cost[ccy]["cost_rt"],
                                    leg_cost[ccy]["fee"], 260.0, d))
        r = pd.concat(legs, axis=1).sum(axis=1) / (2 * params["top"])
        legs2 = [net_returns(w[ccy], rets[ccy], leg_cost[ccy]["cost_rt"], leg_cost[ccy]["fee"],
                             260.0, None, 2.0) for ccy in closes.columns]
        r2 = pd.concat(legs2, axis=1).sum(axis=1) / (2 * params["top"])
        tid = f"{var}:FX{len(closes.columns)}"
        m = evaluate(r, r2, 260.0)
        trials.append({"id": tid, "family": fam, "variant": var, "params": params,
                       "symbol": ",".join(closes.columns), "period": "D1", "bars_per_year": 260.0,
                       "cost_rt_bps": round(float(np.mean([v["cost_rt"] for v in leg_cost.values()])) * 1e4, 2),
                       "fee_annual": None, "carry_from_rates": True, "portfolio": True, **m})
        series[tid] = r[r.index >= pd.Timestamp(START)].astype("float32")

    # Running N and the deflated Sharpe at it.
    if n_prior is None:
        from research.programme import load, status
        reg = load()
        # The register already counts E10's declared trials; N BEFORE this screen excludes them.
        n_prior = status(reg, check_git=False).n_tried - sum(
            int(e.get("trials", 0)) for e in reg.get("experiments", []) if e.get("id") == "E10")
    n_total = int(n_prior) + len(trials)
    sr_std = float(np.std([t["per_obs_sharpe"] for t in trials])) or 1e-9
    for t in trials:
        t["dsr_at_N"] = round(deflated_sharpe_ratio(series[t["id"]].astype(float), n_total, sr_std), 4)

    # PBO per family over all its trials.
    pbo = {}
    for fam in sorted({t["family"] for t in trials}):
        ids = [t["id"] for t in trials if t["family"] == fam]
        M = pd.concat([series[i] for i in ids], axis=1).fillna(0.0).to_numpy()
        pbo[fam] = stats.pbo_cscv(M, n_blocks=16, max_splits=2000) if len(ids) >= 2 else \
            {"pbo": None, "configs": len(ids), "why": "one configuration: PBO undefined"}
        del M

    for t in trials:
        fam_pbo = pbo[t["family"]].get("pbo")
        bar = stats.t_bar(new_family=t["family"] not in F.PUBLISHED)
        checks = {"t_at_least_bar": t["t"] >= bar,
                  "family_pbo_below_half": fam_pbo is not None and fam_pbo < PBO_MAX,
                  "dsr_at_N_at_least_half": t["dsr_at_N"] >= DSR_SCREEN,
                  "survives_double_costs": t["sharpe_double_costs"] > 0}
        t["t_bar"], t["checks"] = bar, checks
        if all(checks.values()):
            t["verdict"] = "IN"
        elif t["sharpe_upper95"] < SHARPE_WORTHWHILE:
            t["verdict"] = "OUT"
        else:
            t["verdict"] = "UNDECIDED"

    if record:
        from research.registry import FailureRegistry
        reg = FailureRegistry()
        for t in trials:
            tid = reg.record_trial(f"E10_{t['variant']}", t["params"], t["symbol"][:60], t["period"],
                                   stage="programme_E10", per_obs_sharpe=t["per_obs_sharpe"],
                                   n_bars=t["n"])
            reg.set_trial_dsr(tid, t["dsr_at_N"])

    counts = {v: sum(1 for t in trials if t["verdict"] == v) for v in ("IN", "OUT", "UNDECIDED")}
    fams = {}
    for fam in sorted({t["family"] for t in trials}):
        ts = [t for t in trials if t["family"] == fam]
        fams[fam] = {"trials": len(ts), "pbo": pbo[fam].get("pbo"),
                     "best_t": max(t["t"] for t in ts),
                     "median_sharpe": round(float(np.median([t["sharpe"] for t in ts])), 3),
                     **{v: sum(1 for t in ts if t["verdict"] == v) for v in ("IN", "OUT", "UNDECIDED")}}
    candidates = [{k: t[k] for k in ("id", "family", "variant", "params", "symbol", "period",
                                     "bars_per_year", "cost_rt_bps", "mean", "sd", "t", "sharpe",
                                     "dsr_at_N")} for t in trials if t["verdict"] == "IN"]
    return {"experiment": "E10", "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sample": [START, END], "instruments": len(syms), "trials": len(trials),
            "n_before": int(n_prior), "n_after": n_total, "verdicts": counts, "families": fams,
            "pbo": pbo, "candidates": candidates,
            "verdict": "PASS" if candidates else "FAIL",
            "seconds": round(time.time() - t0, 1),
            "trials_detail": sorted(trials, key=lambda t: -t["t"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/results/E10-family-screen.json")
    ap.add_argument("--record", action="store_true", help="add the trials to research.db (N)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    res = screen(record=a.record)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"E10: {res['trials']} trials on {res['instruments']} instruments, N {res['n_before']} -> "
          f"{res['n_after']}; verdicts {res['verdicts']}; candidates {len(res['candidates'])}")
    for fam, f in res["families"].items():
        print(f"  {fam:12s} trials {f['trials']:3d}  PBO {f['pbo']}  best t {f['best_t']:.2f}  "
              f"IN {f['IN']} OUT {f['OUT']} UNDECIDED {f['UNDECIDED']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
