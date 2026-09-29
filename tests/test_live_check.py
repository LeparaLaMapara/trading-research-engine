"""Live check: the written cost rule, the quote window, and pauses that only ever get added."""
import calendar
import json
import sqlite3

from research import live_check as L


def _db(tmp_path, rows):
    p = tmp_path / "t.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE ticks (ts_utc REAL, symbol TEXT, bid REAL, ask REAL)")
        c.executemany("INSERT INTO ticks VALUES (?,?,?,?)", rows)
    return str(p)


def test_verdict_needs_enough_quotes_before_judging():
    s, why = L.cost_verdict({"ticks": 50, "hours": 2, "median_cost_bps": 99}, 2.7)
    assert s == "NO-DATA" and "need" in why


def test_verdict_thresholds():
    enough = {"ticks": 1000, "hours": 12}
    assert L.cost_verdict({**enough, "median_cost_bps": 1.2}, 2.7)[0] == "OK"
    assert L.cost_verdict({**enough, "median_cost_bps": 3.0}, 2.7)[0] == "WARN"
    assert L.cost_verdict({**enough, "median_cost_bps": 5.5}, 2.7)[0] == "PAUSE"
    assert L.cost_verdict({**enough, "median_cost_bps": 5.0}, None)[0] == "NO-DATA"


def test_measured_cost_skips_blackout_hours_and_old_quotes(tmp_path):
    now = calendar.timegm((2026, 9, 29, 23, 30, 0))
    day = calendar.timegm((2026, 9, 29, 0, 0, 0))
    rows = [(day + 10 * 3600 + i, "USDSGD", 1.2780, 1.2781) for i in range(10)]     # 0.78 bps
    rows += [(day + 21 * 3600 + i, "USDSGD", 1.2700, 1.2800) for i in range(10)]    # rollover
    rows += [(day - 30 * 86400, "USDSGD", 1.0, 2.0)]                                # too old
    m = L.measured_cost("USDSGD", (20, 23), now, db=_db(tmp_path, rows))
    assert m["ticks"] == 10 and m["hours"] == 1
    assert abs(m["median_cost_bps"] - (0.78 + 0.7)) < 0.02


def test_pauses_are_added_never_removed(tmp_path):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"paused:ETHUSD": "earlier", "peak": 85}))
    report = {"ts": "T", "rules": {
        "ETHUSD": {"cost_status": "OK", "cost_reason": ""},
        "USDSGD": {"cost_status": "PAUSE", "cost_reason": "too dear"}}}
    assert L.apply_pauses(report, str(state)) == ["USDSGD"]
    st = json.loads(state.read_text())
    assert st["paused:ETHUSD"] == "earlier" and "too dear" in st["paused:USDSGD"]
    assert st["peak"] == 85
    assert L.apply_pauses(report, str(state)) == []          # idempotent


def test_live_opens_reads_utc(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join([
        json.dumps({"ts": "2026-09-29T16:41:53Z", "symbol": "USDSGD", "action": "open"}),
        json.dumps({"ts": "2026-09-23T06:00:00Z", "action": "open"}),        # old ETH rows
        json.dumps({"ts": "2026-09-29T16:00:00Z", "symbol": "USDSGD", "action": "dry-run"}),
        "not json"]))
    assert L.live_opens("USDSGD", str(p)) == [calendar.timegm((2026, 9, 29, 16, 41, 53))]
    assert len(L.live_opens("ETHUSD", str(p))) == 1


def test_backtest_facts_from_committed_results():
    f = L.backtest_facts(L.LIVE["USDSGD"])
    assert f["assumed_cost_bps"] == 2.7 and f["trades_per_year"] > 10
    assert L.backtest_facts(L.LIVE["ETHUSD"])["trades_per_year"] > 10


def test_trader_honours_pause_marker():
    src = open("scripts/trader_step.py", encoding="utf-8").read()
    assert 'st.get(f"paused:{SYMBOL}")' in src
