"""E15 on synthetic prices: a planted Ethereum clock pattern is found and passes the vault;
noise fails; the rule count matches the pre-registration."""
import numpy as np
import pandas as pd

from research import e15_crypto as E

NY = "America/New_York"


def fake(plant: bool, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2017-08-15", "2026-10-02", freq="h", tz="UTC")
    local = idx.tz_convert(NY)
    out = {}
    for s, (_, spread) in E.SYMS.items():
        step = rng.normal(0, 50e-4, len(idx))
        if plant and s == "ETHUSD":
            step = step + np.where(np.isin(local.hour, [2, 3, 4]), 25e-4, 0)
        mid = 2000 * np.exp(np.cumsum(step))
        out[s] = pd.DataFrame({"bid": mid * (1 - spread / 2), "ask": mid * (1 + spread / 2)}, index=idx)
    return out


def test_planted_found(tmp_path):
    res = E.run(quotes=fake(True, 5), log_path=str(tmp_path / "v"), n_prior=0, log=lambda *_: None)
    assert res["rules_searched"] == 10944
    assert any(c.startswith("ETHUSD:e7:k3:buy") for c in res["forward_candidates"]), res["forward_candidates"]


def test_noise_fails(tmp_path):
    res = E.run(quotes=fake(False, 6), log_path=str(tmp_path / "v"), n_prior=0, log=lambda *_: None)
    assert res["verdict"] == "FAIL"
