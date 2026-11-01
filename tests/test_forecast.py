"""E16 scoreboard: the hash chain catches edits; one full hourly cycle on synthetic data
locks predictions, then the next hour resolves and scores them."""
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from forecast import cycle as C, features as F, ledger as L, model as M, players as P
from market.bars import SCHEMA


def test_chain_detects_edit(tmp_path):
    p = str(tmp_path / "l.jsonl")
    L.append([{"kind": "x", "v": 1}, {"kind": "x", "v": 2}], p)
    L.append([{"kind": "x", "v": 3}], p)
    assert L.verify(p) == (True, 3)
    rows = open(p).read().splitlines()
    d = json.loads(rows[1]); d["v"] = 99
    rows[1] = json.dumps(d, sort_keys=True)
    open(p, "w").write("\n".join(rows) + "\n")
    assert L.verify(p) == (False, 1)


@pytest.fixture
def world(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    rng = np.random.default_rng(0)
    syms = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US500", "BTCUSD"]
    end = 1_790_000_000 // 3600 * 3600
    ts = np.arange(end - 400 * 24 * 3600, end, 3600)
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA)
        for s in syms:
            px = 100 * np.exp(np.cumsum(rng.normal(0, 1e-3, len(ts))))
            c.executemany("insert into bars values (?,?,?,?,?,?,?,?)",
                          [(s, "H1", float(t), p, p, p, p, 1) for t, p in zip(ts, px)])
            c.execute("insert into bars values (?,?,?,?,?,?,?,?)", (s, "D1", float(ts[0]), 1, 1, 1, 1, 1))
    monkeypatch.setattr(F, "MARKET_DB", db)
    monkeypatch.setattr(C, "publish", lambda *a, **k: None)      # tests never reach Supabase
    monkeypatch.setattr(C, "LOCK", str(tmp_path / "cycle.lock"))
    monkeypatch.setattr(L, "PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(M, "DIR", str(tmp_path))
    monkeypatch.setattr(M, "CURRENT", str(tmp_path / "cur.json"))
    from news import reader as R
    monkeypatch.setattr(R, "STORE", str(tmp_path / "news.jsonl"))   # empty: the news player has no view
    df = F.make_features(F.load_bars(db), events={"nfp": set(), "cpi": set(), "fomc": set()})
    M.save(M.fit(df), int(df.ts.max()), len(df), P.fit_slopes(df))
    last = {s: float(df[df.symbol == s].open.iloc[-1]) for s in syms}
    return end, last


def test_cycle_locks_then_resolves(world):
    end, last = world
    q0 = {s: {"bid": p * 0.9999, "ask": p * 1.0001} for s, p in last.items()}
    a = C.run(snapshot_fn=lambda h: q0, now_hour=end, log=lambda *_: None)
    assert a["predictions"] == 6 * len(P.PLAYERS) and a["resolved"] == 0
    assert C.run(snapshot_fn=lambda h: q0, now_hour=end, log=lambda *_: None)["skipped"]
    q1 = {s: {"bid": p * 1.001 * 0.9999, "ask": p * 1.001 * 1.0001} for s, p in last.items()}
    for s, p in last.items():                                          # every market traded
        _bar(F.MARKET_DB, s, end, p)
    b = C.run(snapshot_fn=lambda h: q1, now_hour=end + 3600, log=lambda *_: None)
    assert b["resolved"] == 6 * len(P.PLAYERS)
    assert {s["player"] for s in b["scores"]} == set(P.PLAYERS)
    ok, n = L.verify()
    assert ok and n == b["lines"]
    res = [x for x in L.lines() if x["kind"] == "resolution"]
    assert all(abs(r["real_bps"] - 10.0) < 0.01 for r in res)        # every mid rose 0.1%


def _bar(db, sym, ts, px):
    with sqlite3.connect(db) as c:
        c.execute("insert or replace into bars values (?,?,?,?,?,?,?,?)", (sym, "H1", float(ts), px, px, px, px, 1))


def test_closed_market_not_scored_failed_session_writes_nothing(world):
    end, last = world
    q0 = {s: {"bid": p * 0.9999, "ask": p * 1.0001} for s, p in last.items()}
    C.run(snapshot_fn=lambda h: q0, now_hour=end, log=lambda *_: None)
    n_before = len(L.lines())
    assert C.run(snapshot_fn=lambda h: {}, now_hour=end + 3600, log=lambda *_: None)["failed"]
    assert len(L.lines()) == n_before                                  # nothing written
    for s, p in last.items():                                          # only EURUSD traded
        if s == "EURUSD":
            _bar(F.MARKET_DB, s, end, p)
    C.run(snapshot_fn=lambda h: q0, now_hour=end + 3600, log=lambda *_: None)
    res = [x for x in L.lines() if x["kind"] == "resolution"]
    assert {r["status"] for r in res if r["symbol"] == "EURUSD"} == {"ok"}
    assert {r["status"] for r in res if r["symbol"] != "EURUSD"} == {"closed"}


def test_partial_last_line_set_aside(tmp_path):
    p = str(tmp_path / "l.jsonl")
    L.append([{"kind": "x", "v": 1}], p)
    with open(p, "a") as fh:
        fh.write('{"kind": "x", "v": 2, "pre')                         # crash mid-write
    assert len(L.lines(p)) == 1
    L.append([{"kind": "x", "v": 3}], p)
    assert L.verify(p) == (True, 2)
    assert open(p + ".partial").read().startswith('{"kind": "x", "v": 2')
