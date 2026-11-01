"""The locked record: an append-only file where every line carries the SHA-256 of the line
before it. Change any old line and every later hash stops matching; `verify()` says where.
The newest hash is published hourly to Supabase (server-stamped), so lines cannot be added
afterwards without the published chain disagreeing.
"""
from __future__ import annotations

import hashlib
import json
import os

PATH = "data/forecast/ledger.jsonl"
GENESIS = "0" * 64


def _digest(prev: str, body: dict) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def lines(path: str | None = None) -> list[dict]:
    path = path or PATH
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def head(path: str | None = None) -> tuple[str, int]:
    path = path or PATH
    ls = lines(path)
    return (ls[-1]["sha"], len(ls)) if ls else (GENESIS, 0)


def append(records: list[dict], path: str | None = None) -> tuple[str, int]:
    path = path or PATH
    prev, n = head(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in records:
            body = dict(r)
            sha = _digest(prev, body)
            fh.write(json.dumps({**body, "prev": prev, "sha": sha}, sort_keys=True) + "\n")
            prev, n = sha, n + 1
        fh.flush()
        os.fsync(fh.fileno())
    return prev, n


def verify(path: str | None = None) -> tuple[bool, int]:
    """(ok, number of lines checked). Stops at the first broken line."""
    path = path or PATH
    prev = GENESIS
    ls = lines(path)
    for i, x in enumerate(ls):
        body = {k: v for k, v in x.items() if k not in ("prev", "sha")}
        if x.get("prev") != prev or _digest(prev, body) != x.get("sha"):
            return False, i
        prev = x["sha"]
    return True, len(ls)
