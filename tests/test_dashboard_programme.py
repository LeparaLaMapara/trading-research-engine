"""The dashboard's research programme panel: read from repo files, never breaks the page."""
from __future__ import annotations

import json
import re

import pytest

app_mod = pytest.importorskip("dashboard.app")

DASHES = re.compile("[–—]")


def _write(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def test_missing_register_gives_a_plain_note(tmp_path):
    d = app_mod._programme_data(tmp_path)
    assert d["ok"] is False and "missing" in d["note"]
    html = app_mod._programme_html(d)
    assert "Research programme" in html and "cannot be shown" in html


def test_malformed_register_and_result_do_not_raise(tmp_path):
    _write(tmp_path, "docs/programme/register.json", "{not json")
    assert app_mod._programme_data(tmp_path)["ok"] is False
    _write(tmp_path, "docs/programme/register.json",
           {"budget": 10, "experiments": [
               {"id": "E09", "title": "Broken", "verdict": "FAIL",
                "result": "docs/results/E09-x.md"},
               {"id": "E10", "title": "Running", "verdict": None,
                "result": "docs/results/E10-y.md"},
               "garbage"]})
    _write(tmp_path, "docs/results/E09-x.json", "[1, 2")
    d = app_mod._programme_data(tmp_path)
    assert d["ok"] and d["spent"] == 1 and d["budget"] == 10
    e09, e10 = d["experiments"]
    assert "unreadable" in e09["note"]
    assert e10["verdict"] == "IN PROGRESS" and e10["note"] == ""   # no result yet is normal
    assert "IN PROGRESS" in app_mod._programme_html(d)


def test_real_register_renders_e01_fail_with_plain_criteria():
    d = app_mod._programme_data()
    assert d["ok"], d
    e01 = next(e for e in d["experiments"] if e["id"] == "E01")
    assert e01["verdict"] == "FAIL"
    assert len(e01["criteria"]) == 4 and not any(c["passed"] for c in e01["criteria"])
    assert "Made money after trading costs" in [c["words"] for c in e01["criteria"]]
    html = app_mod._programme_html(d)
    assert "E01" in html and "v-fail" in html and ">FAIL<" in html
    assert "experiments are done" in html
    assert not DASHES.search(html)


def test_measurement_experiment_renders_a_table(tmp_path):
    _write(tmp_path, "docs/programme/register.json",
           {"budget": 10, "experiments": [
               {"id": "E04", "title": "Live fill slippage", "verdict": "PASS",
                "result": "docs/results/E04-slippage.md", "summary": "Measured."}]})
    _write(tmp_path, "docs/results/E04-slippage.json",
           {"measurements": {"n_probes": 30, "mean_adverse_slippage_pips": 0.12,
                             "p95_adverse_slippage_pips": 0.4, "mean_latency_ms": 180.5,
                             "verdict": "PASS"}})
    d = app_mod._programme_data(tmp_path)
    e04 = d["experiments"][0]
    assert e04["criteria"] == [] and len(e04["measurements"]) == 5
    html = app_mod._programme_html(d)
    assert "class='meas'" in html and "Test trades measured" in html and "180.50" in html
    assert "v-pass" in html


def test_page_renders_panel_without_supabase(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_mod.settings, "SUPABASE_URL", "", raising=False)
    c = TestClient(app_mod.app)
    for path in ("/", "/plain"):
        r = c.get(path)
        assert r.status_code == 200
        assert "id='programme'" in r.text and "E01" in r.text and ">FAIL<" in r.text
        assert "__PROGRAMME__" not in r.text and "__PLAIN__" not in r.text
    full = c.get("/").text
    assert "<script>" in full and "Archive: the old daily search" in full
    assert c.get("/api/data").json()["programme"]["ok"] is True
