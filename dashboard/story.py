"""The story at the top of the dashboard: what this is, how it is doing, what it learned.

Written for someone who has never traded and is seeing the page for the first time. Server
rendered, so it reads fully with no script; the small script at the end only adds motion
(numbers count up, the line draws itself, sections slide in) and is skipped for anyone who
asks their phone for reduced motion. No outside scripts or fonts.

Pure: every function takes plain data and returns HTML. Nothing here reads the network or
can reach trading code.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

esc = html.escape

# Short, plain names for the ten tests. The register's titles are written for the owner.
PLAIN_TITLES = {
    "E01": "Does the morning predict the afternoon?",
    "E02": "The same idea on gold, silver and oil",
    "E03": "Can the queue of orders predict the next minute?",
    "E04": "What does a real trade actually cost?",
    "E05": "Follow Ethereum's 20-day direction",
    "E06": "The same rule on eight digital currencies",
    "E07": "Follow Ethereum, but let winners run",
    "E08": "Follow the direction on five currency pairs",
    "E09": "Bet against Ethereum when buyers pay a premium",
}
KIND_WORDS = {"crypto": "digital currencies", "currency": "currency pairs", "metal": "metals",
              "energy": "oil and gas", "index": "share indices"}

# Fixed history. Dates are from the broker's trade record and the experiment register.
JOURNEY = [
    ("7 Aug", "Built", "R180 went in, only to measure what real trading costs."),
    ("22 Sep", "A plan of ten tests", "No more daily guessing: ten ideas, each written down "
               "before it is tested, so luck cannot be dressed up as skill."),
    ("22 Sep", "First real trade", "Ethereum, after its 20-day rule passed the test."),
    ("23 Sep", "Trading on its own", "Thabang topped up to R1,530 and let it run without "
               "asking him."),
    ("29 Sep", "A tougher re-check", "Both rules that had passed were tested again, harder. "
               "Both failed, so they may not open new trades."),
    ("7 Oct", "A loss, as designed", "An Ethereum trade hit its safety price and closed "
              "itself, losing about R102."),
]


def _r(zar: float | None) -> str:
    if zar is None:
        return "?"
    return f"R{zar:,.0f}" if abs(zar) >= 1 else f"R{zar:,.2f}"


def _no_ids(text: str) -> str:
    """'when E07 replaced it' reads as 'when test 7 replaced it'."""
    return re.sub(r"\bE0?(\d+)\b", lambda m: f"test {int(m.group(1))}", text)


def live_rules(reg: dict) -> tuple[list[str], list[str]]:
    """(rules allowed to open trades, rules demoted by an audit). From the register only."""
    exps = [e for e in reg.get("experiments", []) if isinstance(e, dict)]
    demoted: set[str] = set()
    for e in exps:
        if e.get("kind") == "audit" and e.get("verdict") == "FAIL":
            demoted |= set(re.findall(r"\bE\d+\b", str(e.get("audits") or "")))
    live = [e["id"] for e in exps
            if e.get("kind", "strategy") == "strategy" and e.get("verdict") == "PASS"
            and e.get("id") not in demoted
            and "replaced" not in str(e.get("summary") or "")]
    return live, sorted(demoted)


def _currency_words(symbol: str) -> tuple[str, str] | None:
    names = {"USD": "US dollar", "EUR": "euro", "GBP": "British pound", "JPY": "Japanese yen",
             "SGD": "Singapore dollar", "ZAR": "rand", "CHF": "Swiss franc",
             "AUD": "Australian dollar", "CAD": "Canadian dollar", "NZD": "New Zealand dollar"}
    s = (symbol or "").upper()
    if len(s) == 6 and s[:3] in names and s[3:] in names:
        return names[s[:3]], names[s[3:]]
    return None


def _asset(symbol: str) -> str:
    s = symbol.upper()
    for code, word in (("ETH", "Ethereum"), ("BTC", "Bitcoin"), ("XAU", "gold"),
                       ("XAG", "silver"), ("LTC", "Litecoin"), ("ADA", "Cardano")):
        if code in s:
            return word
    return "what it is trading"


def _spark(series: list[dict]) -> str:
    """The money line since the last top-up, as an SVG that draws itself."""
    pts = [p["v"] for p in series if isinstance(p.get("v"), (int, float))]
    start = 0
    for i in range(1, len(pts)):
        if pts[i] > pts[i - 1] * 1.2:            # a deposit, not a gain
            start = i
    pts = pts[start:]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    # Scale from 85% of the top so a R100 dip does not look like a crash.
    base = min(lo, hi * 0.85)
    span = (hi - base) or 1.0
    w, h = 300.0, 64.0
    step = w / (len(pts) - 1)
    xy = [(i * step, h - 4 - (v - base) / span * (h - 8)) for i, v in enumerate(pts)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    area = d + f" L{w:.1f},{h:.1f} L0,{h:.1f} Z"
    lx, ly = xy[-1]
    return (f"<svg class='st-spark' viewBox='0 0 {w:.0f} {h:.0f}' preserveAspectRatio='none' "
            f"role='img' aria-label='Money since the last top-up: from {_r(pts[0])} to "
            f"{_r(pts[-1])}'><path class='st-area' d='{area}'/>"
            f"<path class='st-line' d='{d}'/>"
            f"<circle class='st-dot' cx='{lx:.1f}' cy='{ly:.1f}' r='3.5'/></svg>"
            f"<p class='st-cap'>Since the last top-up: lowest {_r(lo)}, highest {_r(hi)}.</p>")


def _hero(d: dict) -> str:
    fam = d.get("family") or {}
    put, worth, ch = fam.get("put_in_zar"), fam.get("worth_zar"), fam.get("change_zar")
    if worth is None:
        return ("<section class='st-hero'><p class='st-kicker'>A small experiment</p>"
                "<p>The latest numbers could not be loaded. Please refresh in a few minutes."
                "</p></section>")
    dirn = fam.get("direction") or "even"
    if ch is not None and dirn != "even":
        word = "up" if dirn == "up" else "down"
        mood = (f"<p class='st-delta {word}'><span aria-hidden='true'>"
                f"{'&#9650;' if word == 'up' else '&#9660;'}</span> {word} {_r(abs(ch))} "
                f"({abs(fam['change_pct']):.1f}%)</p>")
    else:
        mood = "<p class='st-delta'>About even</p>"
    put_html = (f"<div><p class='st-q'>Put in</p><p class='st-big' data-count='{put:.0f}'>"
                f"{_r(put)}</p></div>") if put is not None else ""
    return (
        "<section class='st-hero rv'>"
        "<h1 class='st-kicker'>Thabang's trading experiment</h1>"
        "<h2 class='st-title'>A small computer program that trades real money by itself, "
        "to learn what works.</h2>"
        f"<div class='st-pair'>{put_html}<div><p class='st-q'>Worth now</p>"
        f"<p class='st-big' data-count='{worth:.0f}'>{_r(worth)}</p></div></div>"
        f"{mood}{_spark(d.get('balance_series') or [])}"
        "</section>")


def _now(d: dict, live: list[str], demoted: list[str]) -> str:
    fam = d.get("family") or {}
    pos = d.get("open_positions") or []
    if fam.get("halted"):
        light, head = "bad", "Switched off for safety"
        body = fam.get("halted_text") or "It stopped itself and will not trade again."
    elif live:
        light, head = "good", "Trading"
        body = "It has a rule that passed every test, and it follows it once a day."
    else:
        light, head = "wait", "Paused: not opening new trades"
        body = ("No rule has passed every test, so it is not allowed to start new trades. "
                "It keeps measuring and testing while it waits.")
    rows = []
    for p in pos:
        pair = _currency_words(p.get("symbol") or "")
        up = (p.get("side") or "").upper() != "SELL"
        if pair:
            what = (f"the {pair[0]} {'rises' if up else 'falls'} against the {pair[1]}")
        else:
            what = f"the price of {_asset(p.get('symbol') or '')} {'rises' if up else 'falls'}"
        risk = p.get("risk_usd")
        zpu = d.get("zar_per_usd") or 18.0
        loss = (f" If it is wrong it closes itself, losing at most about "
                f"{_r(float(risk) * zpu)}.") if risk is not None else ""
        fee = p.get("swap_usd")
        paid = ""
        if isinstance(fee, (int, float)) and abs(fee) * zpu >= 1:
            paid = (f" Holding it overnight has {'earned' if fee > 0 else 'cost'} "
                    f"{_r(abs(fee) * zpu)} so far.")
        since = (p.get("opened_ts") or "")[:10]
        rows.append(f"<li><strong>One trade from before is still open</strong> "
                    f"(since {esc(_day(since))}): it bets {esc(what)}.{esc(loss)}{esc(paid)}"
                    f"</li>")
    safety = fam.get("safety") or ""
    rows.append(f"<li><strong>Safety net.</strong> {esc(safety)} {esc(fam.get('safety_rule', ''))}"
                f"</li>")
    return (f"<section class='st-card rv'><h3 class='st-h'>Right now</h3>"
            f"<p class='st-status'><span class='st-light {light}' aria-hidden='true'></span>"
            f"<strong>{esc(head)}</strong></p><p>{esc(body)}</p>"
            f"<ul class='st-list'>{''.join(rows)}</ul>"
            f"<p class='st-cap'>{esc(fam.get('updated', ''))}</p></section>")


def _day(iso: str) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    try:
        return f"{int(iso[8:10])} {months[int(iso[5:7]) - 1]}"
    except (ValueError, IndexError):
        return iso


def _journey(d: dict) -> str:
    fam = d.get("family") or {}
    items = list(JOURNEY) + [("Today", "Where it stands",
                              f"Worth {_r(fam.get('worth_zar'))}, from {_r(fam.get('put_in_zar'))}"
                              f" put in. Still learning.")]
    li = "".join(f"<li class='rv' style='--i:{i}'><span class='st-date'>{esc(a)}</span>"
                 f"<strong>{esc(b)}</strong><span>{esc(c)}</span></li>"
                 for i, (a, b, c) in enumerate(items))
    return (f"<section class='st-card'><h3 class='st-h'>The story so far</h3>"
            f"<ol class='st-time'>{li}</ol></section>")


def _tests(prog: dict, demoted: list[str], measured: set[str]) -> str:
    if not prog or not prog.get("ok"):
        return ""
    rows = [e for e in prog.get("experiments", []) if e.get("counts")]
    budget = int(prog.get("budget") or 10)
    done = [e for e in rows if e["verdict"] in ("PASS", "FAIL")]
    cells = []
    for i in range(budget):
        if i < len(rows):
            e = rows[i]
            v = e["verdict"]
            cls = ("recheck" if e["id"] in demoted else
                   "pass" if v == "PASS" else "fail" if v == "FAIL" else "open")
        else:
            cls = "left"
        cells.append(f"<span class='st-cell {cls} rv' style='--i:{i}'></span>")
    cards = []
    for n, e in enumerate(rows, 1):
        v = e["verdict"]
        if e["id"] in demoted:
            tag, cls = "Passed, then failed the re-check", "recheck"
        elif v == "PASS" and e["id"] in measured:
            tag, cls = "Measured", "pass"
        elif v == "PASS":
            tag, cls = "Passed", "pass"
        elif v == "FAIL":
            tag, cls = "Failed", "fail"
        else:
            tag, cls = "Running", "open"
        title = PLAIN_TITLES.get(e["id"]) or _no_ids(e["title"])
        cards.append(f"<details class='st-test {cls}'><summary><span class='st-n'>{n}</span>"
                     f"<span class='st-tt'>{esc(title)}</span>"
                     f"<span class='st-tag'>{esc(tag)}</span></summary>"
                     f"<p>{esc(_no_ids(e.get('summary') or ''))}</p></details>")
    left = budget - len(done)
    return (f"<section class='st-card rv'><h3 class='st-h'>Ten tests, {len(done)} done</h3>"
            f"<p>Every idea is written down before it is tested, and only ten are allowed. "
            f"That stops it from trying ideas until one looks good by luck. "
            f"<strong>{left} test{'s' if left != 1 else ''} left.</strong></p>"
            f"<div class='st-cells' aria-hidden='true'>{''.join(cells)}</div>"
            f"<p class='st-legend'><span class='st-cell pass'></span>passed "
            f"<span class='st-cell recheck'></span>passed, then failed a re-check "
            f"<span class='st-cell fail'></span>failed <span class='st-cell left'></span>"
            f"not used yet</p>"
            f"<p class='st-cap'>Tap a test to read what happened.</p>{''.join(cards)}</section>")


def _lessons(d: dict, prog: dict, universe: dict | None, demoted: list[str],
             measured: set[str]) -> str:
    rows = [e for e in (prog or {}).get("experiments", []) if e.get("counts")]
    ideas = [e for e in rows if e["id"] not in measured]
    passed = sum(1 for e in ideas if e["verdict"] == "PASS")
    rechecked = sum(1 for e in ideas if e["id"] in demoted)
    failed = sum(1 for e in ideas if e["verdict"] == "FAIL")
    zpu = d.get("zar_per_usd") or 18.0
    items = [
        (f"{failed} of {len(ideas)}", "Most ideas fail.",
         f"{failed} of the {len(ideas)} trading ideas lost money once real costs were "
         f"counted. That is normal, and it is why only ten tests are allowed."),
        (_r(1.31 * zpu), "Real costs match the plan.",
         f"20 real practice trades cost {_r(1.31 * zpu)} in total, what the tests assumed. "
         f"So the test results are not flattered by pretending trading is free."),
        (f"{rechecked} of {passed}", "Passing once is not enough.",
         f"{rechecked} of the {passed} rules that passed then failed a tougher re-check: "
         f"their wins came from a few good years. Rather than trade on hope, it stopped "
         f"opening trades."),
    ]
    crypto_fee = None
    for r in (universe or {}).get("rows", []):
        if r.get("symbol") == "ETHUSD" and r.get("priced"):
            crypto_fee = abs(r["fee_long_pct_yr"])
    if crypto_fee:
        items.append((f"{crypto_fee:.0f}% a year", "Waiting costs money too.",
                      f"Holding a digital currency overnight has a fee of about "
                      f"{crypto_fee:.0f}% a year. For slow rules that fee, not the trading, "
                      f"is the biggest cost. Some currency pairs pay you instead."))
    li = "".join(f"<li class='rv' style='--i:{i}'><span class='st-num'>{esc(a)}</span>"
                 f"<strong>{esc(b)}</strong> {esc(c)}</li>" for i, (a, b, c) in enumerate(items))
    return (f"<section class='st-card'><h3 class='st-h'>What it has learned</h3>"
            f"<ul class='st-learn'>{li}</ul></section>")


def _afford(d: dict, universe: dict | None) -> str:
    if not universe or not universe.get("fits_at"):
        return ""
    zpu = d.get("zar_per_usd") or 18.0
    total = int(universe.get("symbols") or 0)
    fits = sorted(((float(k), int(v)) for k, v in universe["fits_at"].items()))
    now_kinds: dict[str, int] = {}
    by_sym = {r["symbol"]: r for r in universe.get("rows", [])}
    for s in universe.get("fits_now", []):
        k = by_sym.get(s, {}).get("kind", "other")
        now_kinds[k] = now_kinds.get(k, 0) + 1
    kinds = ", ".join(f"{n} {KIND_WORDS.get(k, k)}" for k, n in now_kinds.items()) or "none"
    bars = []
    for i, (usd, n) in enumerate(fits):
        label = "Now" if i == 0 else f"With {_r(round(usd * zpu, -2))}"
        pct = 100 * n / total if total else 0
        bars.append(f"<li class='rv' style='--i:{i}'><span class='st-bl'>{esc(label)}</span>"
                    f"<span class='st-bar'><i style='--w:{pct:.0f}%'></i></span>"
                    f"<span class='st-bn'>{n}</span></li>")
    return (f"<section class='st-card rv'><h3 class='st-h'>What this money can trade</h3>"
            f"<p>The broker sells {total} markets. With the safety rule (never risk more than 6% "
            f"on one trade), only <strong>{len(universe.get('fits_now', []))}</strong> are small "
            f"enough today: {esc(kinds)}. More money opens more of them.</p>"
            f"<ul class='st-bars'>{''.join(bars)}</ul>"
            f"<p class='st-cap'>Markets that fit the 6% rule at each amount, out of {total}."
            f"</p></section>")


def _health(d: dict, prog: dict) -> str:
    fam = d.get("family") or {}
    grid = d.get("audit_grid") or {}
    last = [row[-1] for row in grid.get("cells", []) if row]
    bad = sum(1 for s in last if s == "FAIL")
    lights = [
        ("good" if not fam.get("stale") else "bad", "Numbers are fresh" if not fam.get("stale")
         else "Numbers are late: the computer may be off"),
        ("good" if last and not bad else ("wait" if not last else "bad"),
         f"Self-checks today: {len(last) - bad} of {len(last)} fine" if last
         else "Self-checks have not reported today"),
        ("bad" if fam.get("halted") else "good",
         "Safety switch has tripped" if fam.get("halted") else "Safety switch is armed"),
    ]
    if prog and prog.get("ok"):
        left = int(prog.get("budget") or 10) - int(prog.get("spent") or 0)
        lights.append(("wait" if left else "bad", f"{left} research test left"
                       if left == 1 else f"{left} research tests left"))
    li = "".join(f"<li><span class='st-light {c}' aria-hidden='true'></span>{esc(t)}</li>"
                 for c, t in lights)
    return (f"<section class='st-card rv'><h3 class='st-h'>Is it healthy?</h3>"
            f"<ul class='st-lights'>{li}</ul></section>")


def read_universe(root: Path) -> dict | None:
    try:
        return json.loads((root / "docs" / "results" / "universe.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def story_html(d: dict, prog: dict, reg: dict, universe: dict | None) -> str:
    live, demoted = live_rules(reg or {})
    measured = {e.get("id") for e in (reg or {}).get("experiments", [])
                if isinstance(e, dict) and e.get("kind") == "measurement"}
    return ("<div class='st' id='story'>" + _hero(d) + _now(d, live, demoted) + _journey(d)
            + _tests(prog, demoted, measured) + _lessons(d, prog, universe, demoted, measured) + _afford(d, universe)
            + _health(d, prog) + "</div>" + STORY_CSS + STORY_JS)


STORY_CSS = """<style>
.st{display:grid;gap:14px;margin:6px 0 8px}
.st p{margin:0 0 10px}
.st-hero{padding:22px 4px 6px}
.st-kicker{margin:0;color:var(--clay);font-weight:700;font-size:13px;letter-spacing:.08em;
  text-transform:uppercase}
.st-title{font-size:clamp(24px,5.4vw,36px);line-height:1.15;letter-spacing:-.02em;
  margin:2px 0 18px;max-width:20ch}
.st-pair{display:flex;gap:28px;flex-wrap:wrap}
.st-q{color:var(--muted);font-size:14px;margin:0!important}
.st-big{font-size:clamp(38px,9vw,56px);font-weight:700;letter-spacing:-.03em;line-height:1.05;
  font-variant-numeric:tabular-nums}
.st-delta{font-weight:650;font-size:18px}
.st-delta.up{color:var(--good)} .st-delta.down{color:var(--bad)}
.st-spark{width:100%;height:72px;display:block;margin-top:6px;overflow:visible}
.st-line{fill:none;stroke:var(--clay);stroke-width:2.5;stroke-linejoin:round;
  vector-effect:non-scaling-stroke}
.st-area{fill:var(--clay);fill-opacity:.12}
.st-dot{fill:var(--clay)}
.st-cap{color:var(--muted);font-size:13px}
.st-card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}
.st-h{font-size:19px;margin:0 0 10px;letter-spacing:-.01em}
.st-status{display:flex;align-items:center;gap:10px;font-size:18px}
.st-light{width:14px;height:14px;border-radius:50%;flex:none;display:inline-block;
  background:var(--muted)}
.st-light.good{background:var(--good);animation:st-pulse 2.4s infinite}
.st-light.wait{background:#d99a2b;animation:st-pulse 2.4s infinite}
.st-light.bad{background:var(--bad)}
@keyframes st-pulse{0%,100%{opacity:1}50%{opacity:.45}}
.st-list{margin:6px 0 10px;padding-left:20px}
.st-list li{margin-bottom:8px}
.st-time{list-style:none;margin:0;padding:0 0 0 22px;position:relative}
.st-time::before{content:'';position:absolute;left:6px;top:6px;bottom:6px;width:2px;
  background:var(--line)}
.st-time li{position:relative;padding:0 0 16px;display:grid;gap:1px}
.st-time li::before{content:'';position:absolute;left:-21px;top:5px;width:12px;height:12px;
  border-radius:50%;background:var(--card);border:2.5px solid var(--clay)}
.st-time li:last-child::before{background:var(--clay)}
.st-date{color:var(--clay);font-size:13px;font-weight:700}
.st-time span:last-child{color:var(--muted);font-size:15px}
.st-cells{display:grid;grid-template-columns:repeat(10,1fr);gap:6px;margin:12px 0 8px}
.st-cell{display:inline-block;aspect-ratio:1;border-radius:6px;background:var(--line);min-width:12px}
.st-cell.pass{background:var(--good)} .st-cell.fail{background:var(--bad)}
.st-cell.recheck{background:linear-gradient(135deg,var(--good) 50%,var(--bad) 50%)}
.st-cell.open{background:var(--clay)}
.st-cell.left{background:transparent;border:2px dashed var(--muted)}
.st-legend{font-size:13px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 12px;
  align-items:center}
.st-legend .st-cell{width:12px;height:12px;border-radius:3px;margin-right:-6px;vertical-align:-1px}
.st-test{border-top:1px solid var(--line)}
.st-test summary{list-style:none;cursor:pointer;display:grid;
  grid-template-columns:28px 1fr auto;gap:10px;align-items:center;padding:12px 0;min-height:44px}
.st-test summary::-webkit-details-marker{display:none}
.st-n{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-size:13px;
  font-weight:700;color:#fff;background:var(--muted)}
.st-test.pass .st-n{background:var(--good)} .st-test.fail .st-n{background:var(--bad)}
.st-test.recheck .st-n{background:linear-gradient(135deg,var(--good) 50%,var(--bad) 50%)}
.st-tt{font-weight:600;line-height:1.3}
.st-tag{font-size:12px;color:var(--muted);text-align:right;max-width:9.5em;line-height:1.25}
.st-test p{color:var(--muted);font-size:15px;margin:0 0 12px 38px}
.st-test[open] p{animation:st-in .35s ease both}
.st-learn{list-style:none;margin:0;padding:0;display:grid;gap:12px;
  grid-template-columns:repeat(2,1fr)}
.st-learn li{border:1px solid var(--line);border-radius:12px;padding:14px;font-size:15px;
  color:var(--muted)}
.st-learn strong{color:var(--ink)}
.st-num{display:block;font-size:28px;font-weight:700;color:var(--clay);letter-spacing:-.02em;
  margin-bottom:4px}
.st-bars{list-style:none;margin:8px 0;padding:0;display:grid;gap:8px}
.st-bars li{display:grid;grid-template-columns:7.5em 1fr 2.2em;gap:10px;align-items:center;
  font-size:14px}
.st-bar{height:12px;border-radius:99px;background:var(--line);overflow:hidden}
.st-bar i{display:block;height:100%;width:var(--w);background:var(--clay);border-radius:99px}
.st-bn{font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
.st-lights{list-style:none;margin:0;padding:0;display:grid;gap:10px;
  grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.st-lights li{display:flex;gap:10px;align-items:center}
@keyframes st-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes st-wipe{from{clip-path:inset(-10% 100% -10% 0)}to{clip-path:inset(-10% -2% -10% 0)}}
@keyframes st-grow{from{width:0}to{width:var(--w)}}
/* motion only when the script is running and the reader has not asked for less */
.st-motion .rv{opacity:0;transform:translateY(14px);
  transition:opacity .6s ease,transform .6s ease;transition-delay:calc(var(--i,0)*70ms)}
.st-motion .rv.seen{opacity:1;transform:none}
.st-motion .st-spark{animation:st-wipe 1.6s ease-out .3s both}
.st-motion .st-dot{animation:st-in .5s ease 1.8s both}
.st-motion .st-bars li.seen i{animation:st-grow 1s ease both;animation-delay:calc(var(--i,0)*120ms)}
@media (prefers-reduced-motion:reduce){.st-light{animation:none!important}}
@media (max-width:520px){.st-card{padding:14px}.st-learn{grid-template-columns:1fr}.st-pair{gap:18px}
  .st-bars li{grid-template-columns:6.5em 1fr 2em}.st-tag{max-width:7em}}
</style>"""

STORY_JS = """<script>
(function(){
  if(matchMedia('(prefers-reduced-motion: reduce)').matches||!('IntersectionObserver' in window))return;
  var root=document.getElementById('story'); if(!root)return;
  root.classList.add('st-motion');
  function count(el){
    var to=+el.getAttribute('data-count'), t0=null, txt=el.textContent;
    if(!isFinite(to))return;
    function f(t){ if(!t0)t0=t; var k=Math.min(1,(t-t0)/1200), e=1-Math.pow(1-k,3);
      el.textContent='R'+Math.round(to*e).toLocaleString('en-ZA').replace(/\\u00a0|\\s/g,',');
      if(k<1)requestAnimationFrame(f); else el.textContent=txt; }
    requestAnimationFrame(f);
  }
  root.querySelectorAll('[data-count]').forEach(count);
  var io=new IntersectionObserver(function(es){es.forEach(function(e){
    if(e.isIntersecting){e.target.classList.add('seen');io.unobserve(e.target);}});},
    {rootMargin:'0px 0px -8% 0px'});
  root.querySelectorAll('.rv').forEach(function(el){io.observe(el);});
})();
</script>"""
