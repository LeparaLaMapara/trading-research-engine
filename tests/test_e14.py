"""E14 on synthetic prices: a planted jobs-day continuation is found and passes the vault;
noise fails; the rule count matches the pre-registration."""
import numpy as np
import pandas as pd

from research import e14_events as E
from research.e13_search import SYMS

NY = "America/New_York"
DAYS = pd.bdate_range("2014-01-01", "2026-09-30")
NFP = [str(d.date()) for d in DAYS if d.weekday() == 4 and d.day <= 7]
CPI = [str(d.date()) for d in DAYS if d.weekday() == 2 and 10 <= d.day <= 16]


def fake(plant: bool, seed: int):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2013-12-30", "2026-10-02", freq="h", tz="UTC")
    local = idx.tz_convert(NY)
    nfp_day = local.normalize().tz_localize(None).isin(pd.to_datetime(NFP))
    out = {}
    for s in SYMS:
        step = rng.normal(0, 4e-4, len(idx))
        if plant and s == "EURUSD":
            # the 08:00 -> 09:00 move on jobs days is followed by 3 more hours the same way
            shock = rng.choice([-1.0, 1.0], len(idx))
            day_sign = pd.Series(np.where(nfp_day & (local.hour == 9), shock, np.nan), index=idx)
            day_sign = day_sign.groupby(local.normalize()).transform("max").to_numpy()
            step = step + np.where(nfp_day & (local.hour == 9), shock * 15e-4, 0)
            step = step + np.where(nfp_day & np.isin(local.hour, [10, 11, 12]),
                                   np.nan_to_num(day_sign) * 6e-4, 0)
        mid = 1.1 * np.exp(np.cumsum(step))
        out[s] = pd.DataFrame({"bid": mid * (1 - 2e-5), "ask": mid * (1 + 2e-5)}, index=idx)
    return out


def test_planted_found(tmp_path):
    res = E.run(quotes=fake(True, 1), nfp=NFP, cpi=CPI, log_path=str(tmp_path / "v"), n_prior=0,
                log=lambda *_: None)
    assert res["rules_searched"] == 6800
    assert any(c.startswith("A:NFP:r15:x18:follow:EURUSD") for c in res["forward_candidates"]), res["forward_candidates"]


def test_noise_fails(tmp_path):
    res = E.run(quotes=fake(False, 2), nfp=NFP, cpi=CPI, log_path=str(tmp_path / "v"), n_prior=0,
                log=lambda *_: None)
    assert res["verdict"] == "FAIL"
