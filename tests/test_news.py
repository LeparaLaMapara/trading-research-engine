"""E17 news reader: feed parsing, the backlog and stale rules, the 'scored before the hour' cut,
the instrument mapping, and the news player locked and scored in a real cycle."""
import math

from forecast import cycle as C, judge as J, ledger as L, players as P
from news import feeds as FD, reader as R
from tests.test_forecast import world  # noqa: F401  (the synthetic market fixture)

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Rates raised</title><link>https://x/1</link><pubDate>Sun, 01 Nov 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;The board &lt;b&gt;raised&lt;/b&gt; rates.&lt;/p&gt;</description></item></channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>CPI</title>
<link href="https://y/2"/><updated>2026-11-01T12:30:00Z</updated><summary>Prices rose</summary></entry></feed>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>Decision</title>
<link>https://z/3</link><dc:date>2026-11-01T14:00:00Z</dc:date></item></rdf:RDF>"""


def test_parse_three_formats():
    a, = FD.parse("fed", RSS)
    assert a["title"] == "Rates raised" and a["summary"] == "The board raised rates." and a["link"] == "https://x/1"
    assert a["published_utc"] == 1793527200.0
    b, = FD.parse("bls_cpi", ATOM)
    assert b["link"] == "https://y/2" and b["published_utc"] == 1793536200.0
    c, = FD.parse("boc", RDF)
    assert c["title"] == "Decision" and c["published_utc"] == 1793541600.0


class Ans:
    model, request_key = "stub", "k"


class Port:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete_json(self, prompt, keys, system=None, max_tokens=512, retries=2):
        self.calls += 1
        return self.reply, [Ans()]


def _feeds(items_by_src):
    return lambda src: [dict(it) for it in items_by_src.get(src, [])]


def _item(src, n, pub):
    return {"id": f"{src}{n}", "source": src, "title": f"t{n}", "link": "", "published_utc": pub, "summary": ""}


def test_backlog_stale_and_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", str(tmp_path / "n.jsonl"))
    monkeypatch.setattr(R, "SOURCES", str(tmp_path / "s.json"))
    reply = {c: 0 for c in R.CODES} | {"USD": 1.0, "EUR": -0.5, "confidence": 0.8, "why": "hike"}
    port, t0 = Port(reply), 1_793_520_000.0
    src = {"fed": [_item("fed", 0, t0 - 100)]}
    first = R.run_once(now=t0, fetch_fn=_feeds(src), text_fn=lambda u: "", port=port, log=lambda *_: None)
    assert first["first_run"] and first["scored"] == 0 and port.calls == 0     # backlog is never scored
    src["fed"] += [_item("fed", 1, t0 + 500), _item("fed", 2, t0 - 3 * 86400)]  # one fresh, one stale
    out = R.run_once(now=t0 + 600, fetch_fn=_feeds(src), text_fn=lambda u: "", port=port, log=lambda *_: None)
    assert out["new_items"] == 2 and out["scored"] == 1 and port.calls == 1
    scored_at = [r for r in R._rows() if r["kind"] == "score"][0]["scored_utc"]
    sig, used = R.signal(int(scored_at) // 3600 * 3600)            # the hour it was scored in: too late
    assert used == [] and sig["USD"] == 0
    h = (int(scored_at) // 3600 + 1) * 3600
    sig, used = R.signal(h)
    w = 0.8 * math.exp(-((h - (t0 + 600)) / 3600) / 6)
    assert used == ["fed1"] and abs(sig["USD"] - w) < 1e-9 and abs(sig["EUR"] + 0.5 * w) < 1e-9
    assert R.signal(h + 25 * 3600)[1] == []                        # older than 24 h: gone


def test_dead_feed_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE", str(tmp_path / "n.jsonl"))
    monkeypatch.setattr(R, "SOURCES", str(tmp_path / "s.json"))
    def boom(src):
        raise OSError("down")
    out = R.run_once(now=1.0, fetch_fn=boom, port=Port({}), log=lambda *_: None)
    assert out["dead_feeds"] == sorted(FD.FEEDS)


def test_instrument_mapping():
    sig = {c: 0.0 for c in R.CODES} | {"USD": 1.0, "EUR": 0.25}
    assert R.instrument_signal("EURUSD", sig) == -0.75
    assert R.instrument_signal("USDJPY", sig) == 1.0
    assert R.instrument_signal("XAUUSD", sig) == -1.0 and R.instrument_signal("USDZAR", sig) == 1.0
    for s in ("BTCUSD", "XBRUSD", "XTIUSD", "US500", "AUS200", "ETHUSD"):
        assert R.instrument_signal(s, sig) == 0.0


def test_news_player_locked_and_scored(world, tmp_path):
    """A scored item before the hour gives the news player a view on the currency pairs only."""
    from tests.test_forecast import _bar
    from forecast import features as F
    end, last = world
    R._append([{"kind": "item", "id": "a", "source": "fed", "title": "t", "link": "", "status": "new",
                "fetched_utc": end - 1800, "published_utc": end - 1900},
               {"kind": "score", "id": "a", "scored_utc": end - 1700, "version": "n1", "confidence": 1.0,
                "scores": {c: 0.0 for c in R.CODES} | {"USD": 1.0}, "why": "", "model": "stub"}])
    q0 = {s: {"bid": p * 0.9999, "ask": p * 1.0001} for s, p in last.items()}
    a = C.run(snapshot_fn=lambda h: q0, now_hour=end, log=lambda *_: None)
    news = [x for x in L.lines() if x.get("player") == "news"]
    assert {x["symbol"] for x in news} == {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD"}
    assert all(x["version"] == "n1" and x["news_items"] == ["a"] for x in news)
    assert a["predictions"] == 6 * len(P.PLAYERS) + 4
    q1 = {s: {"bid": p * 1.001 * 0.9999, "ask": p * 1.001 * 1.0001} for s, p in last.items()}
    for s, p in last.items():
        _bar(F.MARKET_DB, s, end, p)
    b = C.run(snapshot_fn=lambda h: q1, now_hour=end + 3600, log=lambda *_: None)
    assert "news" in {s["player"] for s in b["scores"]}
    j = {v["player"]: v for v in J.judge()}
    assert j["news"]["experiment"] == "E17" and j["news"]["hours"] == 1
    assert j["xgb_v2"]["verdict"].startswith("too early")


def test_holm_step_down():
    lv = J._holm_levels({"a": 0.001, "b": 0.01, "c": 0.04, "d": 0.5})
    assert lv["a"] == 0.05 / 4 and lv["b"] == 0.05 / 3 and lv["c"] == 0.0 and lv["d"] == 0.0


def test_loop_scripts_compile():
    """The standalone loop is never imported by the other tests; a syntax slip once stopped it."""
    import py_compile
    for f in ("scripts/forecast_loop.py", "scripts/engine_loop.py"):
        py_compile.compile(f, doraise=True)
