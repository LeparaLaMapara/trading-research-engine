"""The weekly model download switches only when every check passes."""
import hashlib
import json

import pytest

from forecast import model as M, pull_model as PM


class R:
    def __init__(self, data=None, content=b"", status=200):
        self._d, self.content, self.status_code = data, content, status

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DIR", str(tmp_path))
    monkeypatch.setattr(M, "CURRENT", str(tmp_path / "cur.json"))
    monkeypatch.setattr(PM, "STAMP", str(tmp_path / "stamp"))
    old = tmp_path / "old.json"
    old.write_bytes(b"OLD")
    (tmp_path / "cur.json").write_text(json.dumps({"file": str(old), "sha256": hashlib.sha256(b"OLD").hexdigest(),
                                                  "version": M.VERSION, "trained_to_ts": 100}))
    monkeypatch.setattr(M, "load", lambda: (None, json.loads((tmp_path / "cur.json").read_text())))
    return tmp_path


def serve(monkeypatch, blob, meta, author="github-actions[bot]"):
    rel = {"author": {"login": author}, "assets": [{"name": "model.json", "browser_download_url": "u/model"},
                                                   {"name": "model-meta.json", "browser_download_url": "u/meta"}]}
    def get(url, **kw):
        return R(rel) if url == PM.API else R(meta) if url == "u/meta" else R(content=blob)
    monkeypatch.setattr(PM.requests, "get", get)


def meta_for(blob, ts=200, version=None):
    return {"sha256": hashlib.sha256(blob).hexdigest(), "version": version or M.VERSION, "trained_to_ts": ts}


def current(env):
    return json.loads((env / "cur.json").read_text())["sha256"]


def test_good_release_switches(env, monkeypatch):
    serve(monkeypatch, b"NEW", meta_for(b"NEW"))
    assert "SWITCHED" in PM.check(force=True)
    assert current(env) == hashlib.sha256(b"NEW").hexdigest()


@pytest.mark.parametrize("case", ["hand_made", "bad_hash", "older", "other_version"])
def test_bad_release_keeps_current(env, monkeypatch, case):
    before = current(env)
    blob, meta, author = b"NEW", meta_for(b"NEW"), "github-actions[bot]"
    if case == "hand_made":
        author = "someone"
    if case == "bad_hash":
        meta = {**meta, "sha256": "0" * 64}
    if case == "older":
        meta = meta_for(b"NEW", ts=50)
    if case == "other_version":
        meta = meta_for(b"NEW", version="v1")
    serve(monkeypatch, blob, meta, author)
    PM.check(force=True)
    assert current(env) == before
