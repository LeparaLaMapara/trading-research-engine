import time
from types import SimpleNamespace

from connection import tokens
from news import reader
from scripts import engine_loop as E


def _tokens(monkeypatch, obtained, lifetime=30 * 86400):
    monkeypatch.setattr(tokens, "load", lambda: {"refresh_token": "r", "obtained_at": obtained, "expires_in": lifetime})
    calls = []
    monkeypatch.setattr(tokens, "refresh", lambda t=None: calls.append(t) or {})
    return calls


def test_token_with_time_left_is_not_refreshed(monkeypatch):
    calls = _tokens(monkeypatch, obtained=1000)
    assert tokens.refresh_if_expiring(now=1000 + 10 * 86400) is False
    assert calls == []


def test_token_close_to_expiry_is_refreshed(monkeypatch):
    calls = _tokens(monkeypatch, obtained=1000)
    assert tokens.refresh_if_expiring(now=1000 + 26 * 86400) is True
    assert calls == ["r"]


def test_token_with_no_known_expiry_is_left_alone(monkeypatch):
    calls = _tokens(monkeypatch, obtained=1000, lifetime=None)
    assert tokens.refresh_if_expiring(now=10 ** 10) is False
    assert calls == []


def _engine(monkeypatch, tmp_path, minute=10):
    hour = 1_000_000
    monkeypatch.setattr(time, "time", lambda: hour * 3600.0 + minute * 60)
    monkeypatch.setattr(E, "ROOT", str(tmp_path))
    monkeypatch.setitem(E._forecast, "hour", hour)
    monkeypatch.setitem(E._forecast, "proc", SimpleNamespace(poll=lambda: 0))
    monkeypatch.setitem(E._news, "proc", None)
    monkeypatch.setitem(E._news, "last", 0.0)
    started = []
    monkeypatch.setattr(E.subprocess, "Popen", lambda *a, **k: started.append(a[0]) or SimpleNamespace(poll=lambda: None))
    return started


def test_engine_loop_starts_the_reader_after_the_cycle(monkeypatch, tmp_path):
    started = _engine(monkeypatch, tmp_path)
    E.maybe_news()
    assert started and started[0][-1] == "news.reader"


def test_engine_loop_waits_while_the_cycle_runs(monkeypatch, tmp_path):
    started = _engine(monkeypatch, tmp_path)
    monkeypatch.setitem(E._forecast, "proc", SimpleNamespace(poll=lambda: None))
    E.maybe_news()
    assert started == []


def test_engine_loop_skips_the_end_of_the_hour(monkeypatch, tmp_path):
    started = _engine(monkeypatch, tmp_path, minute=56)
    E.maybe_news()
    assert started == []


def test_engine_loop_reads_once_per_five_minutes(monkeypatch, tmp_path):
    started = _engine(monkeypatch, tmp_path)
    E.maybe_news()
    E._news["proc"] = SimpleNamespace(poll=lambda: 0)
    E.maybe_news()
    assert len(started) == 1


def test_second_reader_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(reader, "LOCK", str(tmp_path / "n" / "reader.lock"))
    assert reader._lock() is True
    assert reader._lock() is False
