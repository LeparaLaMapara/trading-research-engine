import json

from connection import tokens


def _setup(monkeypatch, tmp_path, local, remote):
    p = tmp_path / "tokens.json"
    if local is not None:
        p.write_text(json.dumps(local))
    monkeypatch.setattr(tokens.settings, "TOKEN_STORE", str(p))
    monkeypatch.setattr(tokens, "_remote_load", lambda: remote)


def test_newer_shared_store_beats_a_stale_file(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"access_token": "old", "obtained_at": 100},
           {"access_token": "new", "obtained_at": 200})
    assert tokens.load()["access_token"] == "new"


def test_newer_file_beats_the_store(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"access_token": "file", "obtained_at": 300},
           {"access_token": "store", "obtained_at": 200})
    assert tokens.load()["access_token"] == "file"


def test_file_alone_and_store_alone(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"access_token": "file"}, {})
    assert tokens.load()["access_token"] == "file"
    _setup(monkeypatch, tmp_path / "x", None, {"access_token": "store"})
    (tmp_path / "x").mkdir()
    assert tokens.load()["access_token"] == "store"
