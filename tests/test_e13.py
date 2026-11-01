"""E13 on synthetic prices: a planted clock pattern is found and passes the vault; noise fails;
the vault refuses a second opening."""
import numpy as np
import pandas as pd
import pytest

from research import e13_search as E, vault

NY = "America/New_York"


def fake_quotes(plant: bool, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2013-12-30", "2026-10-02", freq="h", tz="UTC")
    local = idx.tz_convert(NY)
    out = {}
    for i, s in enumerate(E.SYMS):
        step = rng.normal(0, 4e-4, len(idx))
        if plant and s == "EURUSD":
            # +4 bps on the bars opening 02:00-04:00 New York: the move from the 01:00 open to the 04:00 open (slot 7, hold 3)
            step = step + np.where(np.isin(local.hour, [2, 3, 4]) & (local.weekday < 5), 4e-4, 0)
        mid = 1.1 * np.exp(np.cumsum(step))
        out[s] = pd.DataFrame({"bid": mid * (1 - 2e-5), "ask": mid * (1 + 2e-5)}, index=idx)
    return out


def test_planted_pattern_found(tmp_path):
    res = E.run(quotes=fake_quotes(True), log_path=str(tmp_path / "v.jsonl"), n_prior=0,
                log=lambda *_: None)
    assert res["rules_searched"] == 28728
    assert res["verdict"] == "PASS"
    assert any(c.startswith("EURUSD:e7:k3:buy") for c in res["forward_candidates"])


def test_noise_fails(tmp_path):
    res = E.run(quotes=fake_quotes(False, seed=3), log_path=str(tmp_path / "v.jsonl"), n_prior=0,
                log=lambda *_: None)
    assert res["verdict"] == "FAIL"


def test_vault_opens_once(tmp_path):
    log = str(tmp_path / "v.jsonl")
    days = pd.bdate_range("2022-12-01", "2023-02-01")
    m = vault.open_once("EX", [{"id": "a"}], days, log)
    assert m.sum() > 0 and not m[0]
    with pytest.raises(vault.VaultAlreadyOpened):
        vault.open_once("EX", [{"id": "b"}], days, log)
    with pytest.raises(ValueError):
        vault.open_once("EY", [], days, log)
