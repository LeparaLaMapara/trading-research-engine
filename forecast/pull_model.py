"""Fetch the weekly model that GitHub Actions trains (.github/workflows/retrain.yml).

The PC never trains on full history any more; it downloads the small model file from the
rolling release "model-latest" and switches to it only when every check passes:

1. the release was published by the workflow (author github-actions[bot]), not by hand;
2. the file's SHA-256 equals the hash in the release's meta file;
3. the model version equals the code's (forecast/model.py VERSION);
4. it was trained on newer data than the model in use.

Anything else keeps the current model. Downloads are anonymous (public repo, no key on the PC).
Checked at most every 6 hours, from the hourly cycle, before it predicts, so a switch always
happens at an hour boundary.

    python -m forecast.pull_model          # check now
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import requests

from forecast import model as M

REPO = "LeparaLaMapara/trading-research-engine"
API = f"https://api.github.com/repos/{REPO}/releases/tags/model-latest"
STAMP = os.path.join(M.DIR, "pull-checked.txt")
EVERY_S = 6 * 3600


def _current() -> dict:
    try:
        with open(M.CURRENT, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def check(force: bool = False, log=print) -> str:
    """Returns what happened, in one line. Never raises."""
    try:
        if not force and os.path.exists(STAMP) and time.time() - os.path.getmtime(STAMP) < EVERY_S:
            return "model check: not due"
        os.makedirs(M.DIR, exist_ok=True)
        with open(STAMP, "w") as fh:
            fh.write(str(time.time()))
        r = requests.get(API, timeout=30, headers={"Accept": "application/vnd.github+json"})
        if r.status_code == 404:
            return "model check: no release yet"
        r.raise_for_status()
        rel = r.json()
        if (rel.get("author") or {}).get("login") != "github-actions[bot]":
            return "model check: REFUSED, release not published by the workflow"
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if not {"model.json", "model-meta.json"} <= set(assets):
            return "model check: release incomplete"
        meta = requests.get(assets["model-meta.json"], timeout=60).json()
        cur = _current()
        if meta.get("version") != M.VERSION:
            return f"model check: kept current (release is {meta.get('version')}, code is {M.VERSION})"
        if meta.get("sha256") == cur.get("sha256"):
            return "model check: already current"
        if int(meta.get("trained_to_ts", 0)) <= int(cur.get("trained_to_ts", 0)):
            return "model check: kept current (release is not newer)"
        blob = requests.get(assets["model.json"], timeout=300).content
        if hashlib.sha256(blob).hexdigest() != meta.get("sha256"):
            return "model check: REFUSED, file does not match its hash"
        final = os.path.join(M.DIR, f"model-{meta['sha256'][:16]}.json")
        with open(final + ".tmp", "wb") as fh:
            fh.write(blob)
        os.replace(final + ".tmp", final)
        new = {**meta, "file": final, "source": f"github release model-latest, commit {meta.get('commit', '')[:12]}"}
        with open(M.CURRENT + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(new, fh)
        os.replace(M.CURRENT + ".tmp", M.CURRENT)
        try:
            M.load()                                        # must load and match its hash
        except Exception:
            with open(M.CURRENT, "w", encoding="utf-8") as fh:
                json.dump(cur, fh)                          # put the old model back
            return "model check: REFUSED, new model would not load; old model restored"
        return f"model check: SWITCHED to {meta['sha256'][:16]} (trained to {meta.get('trained_to_ts')})"
    except Exception as e:                                  # never stop the hourly record
        return f"model check: failed ({type(e).__name__}); kept current"


if __name__ == "__main__":
    print(check(force=True))
