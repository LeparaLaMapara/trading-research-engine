"""The family section: plain words, rand amounts, graceful with missing numbers."""
from __future__ import annotations

import html as H
import re

import pytest

app_mod = pytest.importorskip("dashboard.app")

NOW = 1790150400.0                       # 2026-09-23 08:00 UTC, a fixed clock for the tests
TS_12_MIN_AGO = "2026-09-23T07:48:00+00:00"
DASHES = re.compile("[–—]")
ZAR = app_mod.ZAR_PER_USD


def _acct(**kw):
    row = {"ts": TS_12_MIN_AGO, "balance": 85.12, "equity": 84.73, "currency": "USD",
           "deposited_usd": 85.0, "peak_equity": 85.13, "halted": None}
    row.update(kw)
    return row


POS = {"symbol": "ETHUSD", "side": "BUY", "entry_price": 2766.94, "current_price": 2758.72,
       "stop_loss": 2598.35, "take_profit": None, "unrealised_usd": -0.25, "risk_usd": 5.0577,
       "status": "OPEN"}


def _text(fragment: str) -> str:
    return H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def _banned_hits(text: str) -> list[str]:
    hits = []
    for w in app_mod.FAMILY_BANNED:
        flags = 0 if w == "None" else re.I
        if re.search(rf"\b{re.escape(w)}\b", text, flags):
            hits.append(w)
    return hits


def test_headline_with_deposit_known():
    fam = app_mod._family(_acct(), [POS], now=NOW)
    assert fam["put_in_zar"] == pytest.approx(85.0 * ZAR)
    assert fam["worth_zar"] == pytest.approx(84.73 * ZAR)
    assert fam["direction"] == "down"
    out = app_mod._family_html(fam)
    txt = _text(out)
    assert "Put in R1,530" in txt and "Worth now R1,525" in txt
    assert "Down" in txt and "R5" in txt and "&#9660;" in out and "fam-tile down" in out
    assert "12 minutes ago" in txt


def test_headline_up_and_even():
    up = app_mod._family(_acct(equity=100.0), [], now=NOW)
    assert up["direction"] == "up"
    assert "&#9650;" in app_mod._family_html(up) and "fam-tile up" in app_mod._family_html(up)
    even = app_mod._family(_acct(equity=85.03), [], now=NOW)      # 54 cents off: within R1
    assert even["direction"] == "even"
    assert "About even" in app_mod._family_html(even)


def test_equity_missing_falls_back_to_balance():
    fam = app_mod._family(_acct(equity=None), [], now=NOW)
    assert fam["worth_zar"] == pytest.approx(85.12 * ZAR)


@pytest.mark.parametrize("dep", [None, "", 0, "nan"])
def test_headline_when_deposit_unknown(dep):
    fam = app_mod._family(_acct(deposited_usd=dep, peak_equity=None), [POS], now=NOW)
    assert fam["put_in_zar"] is None and fam["direction"] is None
    txt = _text(app_mod._family_html(fam))
    assert "Worth now R1,525" in txt
    assert "Put in" not in txt and "R0" not in txt
    assert "still being fetched" in txt


def test_no_account_row_at_all():
    fam = app_mod._family(None, [], now=NOW)
    txt = _text(app_mod._family_html(fam))
    assert "could not be loaded" in txt and "not known yet" in txt
    assert "R0" not in txt and not _banned_hits(txt)


def test_open_position_sentence_uses_risk():
    fam = app_mod._family(_acct(), [POS], now=NOW)
    assert fam["doing"] == ("It is betting Ethereum's price goes up. If it is wrong, it gets "
                            "out automatically, losing at most about R91.")
    short = app_mod._family(_acct(), [{**POS, "side": "SELL", "risk_usd": None}], now=NOW)
    assert "goes down" in short["doing"] and "price set in advance" in short["doing"]


def test_no_position_waits():
    fam = app_mod._family(_acct(), [], now=NOW)
    assert fam["doing"] == "It is waiting for its next signal. It checks once a day."


@pytest.mark.parametrize("reason,words", [
    ("equity $19.50 below the $20 floor on 2026-10-01", "least it is allowed to trade with"),
    ("drawdown 41% from the $85.13 peak on 2026-10-01", "40% below the most it has ever"),
    ("something new", "safety limits was reached"),
])
def test_halted_notice(reason, words):
    fam = app_mod._family(_acct(halted=reason), [POS], now=NOW)
    out = app_mod._family_html(fam)
    assert "class='fam-halt'" in out
    txt = _text(out)
    assert "The program has stopped itself for safety:" in txt and words in txt
    assert "It will not trade again unless Thabang restarts it." in txt
    assert "betting" not in txt                     # no stale "what it is doing" line
    assert not _banned_hits(txt), _banned_hits(txt)


def test_max_loss_computation():
    f = app_mod.max_loss_usd
    assert f(84.73, 85.13) == pytest.approx(84.73 - 0.6 * 85.13)       # 40% below peak binds
    assert f(30.0, 30.0) == pytest.approx(10.0)                        # $20 floor binds
    assert f(84.73, None) == pytest.approx(84.73 * 0.4)                # no peak: use equity
    assert f(100.0, 85.0) == pytest.approx(40.0)                       # stale peak below equity
    assert f(15.0, 100.0) == 0.0                                       # already past the line
    assert f(None, 100.0) is None
    fam = app_mod._family(_acct(), [], now=NOW)
    assert fam["max_loss_zar"] == pytest.approx((84.73 - 0.6 * 85.13) * ZAR)
    assert "about R606" in fam["safety"]
    assert "6% of the money on one trade" in fam["safety_rule"]


def test_stale_numbers_are_flagged():
    fam = app_mod._family(_acct(ts="2026-09-23T01:00:00+00:00"), [], now=NOW)
    assert fam["stale"] and "longer than usual" in fam["updated"]


def test_family_text_has_no_jargon_or_dashes():
    for acct, pos in [(_acct(), [POS]), (_acct(deposited_usd=None), []),
                      (_acct(halted="drawdown 45% from the $85 peak"), [POS]), (None, [])]:
        txt = _text(app_mod._family_html(app_mod._family(acct, pos, now=NOW)))
        assert not _banned_hits(txt), (_banned_hits(txt), txt)
        assert not DASHES.search(txt)


def test_healthz_makes_no_supabase_call(monkeypatch):
    from fastapi.testclient import TestClient

    def boom(*a, **k):
        raise AssertionError("healthz must not touch Supabase")
    monkeypatch.setattr(app_mod, "_sb", boom)
    r = TestClient(app_mod.app).get("/healthz")
    assert r.status_code == 200 and r.text == "ok"
    assert r.headers["content-type"].startswith("text/plain")


def _visible(page: str) -> str:
    return re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", page, flags=re.S)


def test_pages_lead_with_family_section(monkeypatch):
    from fastapi.testclient import TestClient
    rows = {"trading_account": [_acct()], "trading_positions": [POS]}
    monkeypatch.setattr(app_mod, "_sb", lambda table, *a, **k: list(rows.get(table, [])))
    c = TestClient(app_mod.app)
    for path in ("/", "/plain"):
        page = c.get(path).text
        fam = re.search(r"<section class='fam'.*?</section>", page, re.S).group(0)
        # The family section comes before any technical block.
        assert page.index("id='family'") < page.index("<details")
        assert page.index("id='family'") < page.index("id='programme'")
        txt = _text(fam)
        assert "Put in R1,530" in txt and "losing at most about R91" in txt
        assert not _banned_hits(txt)
        assert not DASHES.search(_visible(page)), DASHES.findall(_visible(page))
    full = c.get("/").text
    # Technical parts sit inside <details>, and the charts redraw when one opens.
    for title in ("Research experiments: what was tried, what passed and failed",
                  "Is the system healthy?", "Charts: money over time", "Technical table",
                  "Archive of the old daily search"):
        assert f"<summary>{title}" in full
    assert "addEventListener('toggle'" in full


def test_pages_graceful_without_supabase(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_mod.settings, "SUPABASE_URL", "", raising=False)
    c = TestClient(app_mod.app)
    for path in ("/", "/plain"):
        r = c.get(path)
        assert r.status_code == 200
        txt = _text(re.search(r"<section class='fam'.*?</section>", r.text, re.S).group(0))
        assert "could not be loaded" in txt and "R0" not in txt
        assert "__FAMILY__" not in r.text


def test_null_take_profit_never_prints_none(monkeypatch):
    from fastapi.testclient import TestClient
    rows = {"trading_account": [_acct()], "trading_positions": [POS]}
    monkeypatch.setattr(app_mod, "_sb", lambda table, *a, **k: list(rows.get(table, [])))
    c = TestClient(app_mod.app)
    for path in ("/", "/plain"):
        # "None of this happened." in the archive is English; "or None" would be a leak.
        assert not re.search(r"(at|or|to|if it) None\b", _visible(c.get(path).text))
    assert "no profit target" in c.get("/api/data").json()["why_no_trade"]
