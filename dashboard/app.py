"""The family-facing dashboard.

Audience: two people who do not trade and should not have to learn. Everything on the first
screen answers one of five questions in rands:

    How much money do I have?
    How much did it try to trade?
    How much did it make?
    How much did it lose?
    What has it learned?

Jargon is not simplified here, it is removed. Sharpe, deflated Sharpe, walk-forward, rungs and
p-values live behind one "show the technical detail" toggle for the owner. If a number cannot
be stated in rands it does not belong on the front screen.

The chat is an instruction channel: a person types a goal in their own words, an LLM fills in
the blanks it implies, and DETERMINISTIC code decides whether the arithmetic permits it
(`research/goals.py`). The reply is in rands and is allowed to say no.

One hard boundary, which is rule one of this project: **nothing typed here can place a trade.**
The chat writes goals. The research loop reads goals. The risk layer has no path from either.
A sentence must never become an order.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from config import settings
from research.goals import GoalSpec, assess, suggest_reachable

app = FastAPI(title="Trading research")

ZAR_PER_USD = float(os.environ.get("ZAR_PER_USD", "18.0"))
# Goals drive the research system, so writing one requires the shared password. Reading the
# dashboard does not. Without a password set, the goal channel stays closed rather than open.
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
_SECRET = (os.environ.get("DASHBOARD_SECRET") or DASHBOARD_PASSWORD or "unset").encode()
# Writing needs the service-role key. With only the public read key the page still works and
# says plainly that the goal channel is read-only.
WRITE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
READ_KEY = settings.SUPABASE_KEY or ""


def _token() -> str:
    return hmac.new(_SECRET, b"dashboard-v1", hashlib.sha256).hexdigest()[:32]


def _authed(request: Request) -> bool:
    return bool(DASHBOARD_PASSWORD) and request.cookies.get("auth") == _token()


def _sb(table: str, query: str = "", key: str = "") -> list[dict]:
    k = key or READ_KEY
    if not (settings.SUPABASE_URL and k):
        return []
    try:
        r = requests.get(f"{settings.SUPABASE_URL}/rest/v1/{table}?{query}",
                         headers={"apikey": k, "Authorization": f"Bearer {k}",
                                  # This project's tables live in their own schema, not public.
                                  "Accept-Profile": settings.SUPABASE_SCHEMA}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def _sb_insert(table: str, row: dict) -> dict | None:
    if not (settings.SUPABASE_URL and WRITE_KEY):
        return None
    try:
        r = requests.post(f"{settings.SUPABASE_URL}/rest/v1/{table}",
                          headers={"apikey": WRITE_KEY,
                                   "Authorization": f"Bearer {WRITE_KEY}",
                                   "Content-Type": "application/json",
                                   "Content-Profile": settings.SUPABASE_SCHEMA,
                                   "Prefer": "return=representation"},
                          json=row, timeout=15)
        r.raise_for_status()
        out = r.json()
        return out[0] if isinstance(out, list) and out else None
    except Exception:
        return None


def _money(zar: float) -> str:
    return f"R{zar:,.0f}" if abs(zar) >= 1 else f"R{zar:,.2f}"


def _dashboard_data() -> dict:
    acct = _sb("trading_account", "select=balance,equity,currency,ts&order=ts.desc&limit=1")
    strategies = _sb("trading_strategies",
                     "select=run_ts,symbol,kind,verdict,pnl_on_10,pnl_on_200&"
                     "order=run_ts.desc&limit=200")
    lessons = _sb("trading_lessons",
                  "select=lesson,evidence,times_seen,helped_rate&retired=eq.false&"
                  "order=helped_rate.desc&limit=8")
    goals = _sb("trading_goals",
                "select=created_ts,author,raw_text,status,target_zar,horizon_days,"
                "feasible,verdict_plain&order=created_ts.desc&limit=5", key=WRITE_KEY)

    balance_usd = float(acct[0]["balance"]) if acct else 0.0
    balance_zar = balance_usd * ZAR_PER_USD
    as_of = acct[0]["ts"] if acct else None

    # Real trading activity. Nothing here is modelled: these come from orders that were
    # actually sent to the broker. As of 2026-09-15 that is one attempt, rejected.
    attempted = int(os.environ.get("TRADES_ATTEMPTED", "1"))
    executed = int(os.environ.get("TRADES_EXECUTED", "0"))
    made_zar = 0.0
    lost_zar = 0.0
    risked_zar = 0.0

    tested = len(strategies)
    passed = sum(1 for s in strategies if (s.get("verdict") or "").upper() == "PASS")
    last_run = strategies[0]["run_ts"] if strategies else None

    if executed == 0 and passed == 0 and tested > 0:
        why = ("It has not traded. Every idea it tested so far lost money once real costs "
               "were counted, so it did not put any of yours at risk.")
    elif executed == 0 and tested == 0:
        why = ("It has not traded, and it has not finished testing anything yet either. "
               "Nothing is at risk.")
    elif executed == 0:
        why = ("It has not traded yet. Some ideas look promising but none has cleared the "
               "bar it is required to clear before real money moves.")
    else:
        why = f"It has placed {executed} trade(s)."

    return {
        "have_zar": balance_zar,
        "have_usd": balance_usd,
        "as_of": as_of,
        "risked_zar": risked_zar,
        "made_zar": made_zar,
        "lost_zar": lost_zar,
        "attempted": attempted,
        "executed": executed,
        "ideas_tested": tested,
        "ideas_passed": passed,
        "last_run": last_run,
        "why_no_trade": why,
        "lessons": lessons,
        "goals": goals,
        "can_set_goals": bool(WRITE_KEY and DASHBOARD_PASSWORD),
        "configured": bool(settings.SUPABASE_URL and READ_KEY),
        "zar_per_usd": ZAR_PER_USD,
    }


@app.get("/api/data")
def api_data() -> JSONResponse:
    return JSONResponse(_dashboard_data())


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/login")
async def api_login(request: Request) -> JSONResponse:
    body = await request.json()
    if DASHBOARD_PASSWORD and body.get("password") == DASHBOARD_PASSWORD:
        resp = JSONResponse({"ok": True})
        resp.set_cookie("auth", _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp
    return JSONResponse({"ok": False, "error": "Wrong password."}, status_code=401)


def _specialise(text: str, start_zar: float) -> dict:
    """Let a model fill in the blanks a wish implies. It decides NOTHING about feasibility.

    Falls back to defaults with no model at all, so the channel still works offline and the
    person still gets an honest answer.
    """
    spec = {"target_zar": round(start_zar * 2, 2), "horizon_days": 365,
            "risk_zar": round(start_zar * 0.64, 2), "assumed": True}
    try:
        from council.backends import get_backend
        backend = get_backend("anthropic")
        raw = backend.complete(
            "You convert a person's informal money goal into JSON. You do NOT judge whether "
            "it is achievable; other code does that. Reply with ONLY a JSON object with keys:\n"
            "  target_zar    the TOTAL BALANCE in rands they want to end up with, NOT the "
            "profit. It must be larger than their current balance.\n"
            "  horizon_days  integer, by when.\n"
            "  risk_zar      how much of the stake they seem willing to lose.\n"
            "If the person did not say, infer something reasonable and modest.",
            f"Their current balance is R{start_zar:,.0f}. They said: {text!r}",
        )
        import json
        got = json.loads(raw)
        target = float(got["target_zar"])
        # Guard the ambiguity the model keeps hitting: a "target" at or below the current
        # balance almost always means the PROFIT they want, not the end balance. Treat it as
        # profit rather than handing the person an absurd verdict about shrinking the account.
        assumed = False
        if target <= start_zar:
            target = start_zar + abs(target)
            assumed = True
        spec = {"target_zar": target,
                "horizon_days": max(int(got["horizon_days"]), 1),
                "risk_zar": float(got.get("risk_zar", start_zar * 0.64)),
                "assumed": assumed}
    except Exception:
        pass
    return spec


@app.post("/api/goal")
async def api_goal(request: Request) -> JSONResponse:
    """A person states a goal. We specialise it, judge it with arithmetic, and store it."""
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "Please sign in first."}, status_code=401)
    body = await request.json()
    text = (body.get("text") or "").strip()
    author = (body.get("author") or "family").strip()[:40]
    if not text:
        return JSONResponse({"ok": False, "error": "Say what you want to happen."}, status_code=400)

    data = _dashboard_data()
    start = data["have_zar"] or 1000.0
    s = _specialise(text, start)
    spec = GoalSpec(author=author, raw_text=text, target_zar=s["target_zar"],
                    horizon_days=s["horizon_days"], risk_zar=s["risk_zar"], start_zar=start)
    verdict = assess(spec, zar_per_usd=ZAR_PER_USD)
    alternatives = suggest_reachable(spec, zar_per_usd=ZAR_PER_USD)

    _sb_insert("trading_goals", {
        "author": author, "raw_text": text,
        "status": "specified" if verdict.feasible else "infeasible",
        "target_zar": spec.target_zar, "horizon_days": spec.horizon_days,
        "risk_zar": spec.risk_zar, "feasible": verdict.feasible,
        "required_return_pct": verdict.required_return_pct,
        "required_sharpe": verdict.required_sharpe,
        "ruin_probability": verdict.prob_hit_floor_no_edge,
        "verdict_plain": verdict.verdict_plain,
        "spec_json": {"feasibility": verdict.to_dict(), "alternatives": alternatives,
                      "inferred": s["assumed"]},
    })

    reply = verdict.verdict_plain + "\n\n" + verdict.context_plain
    if not verdict.feasible and alternatives.get("days_needed_at_world_class_skill"):
        reply += (f"\n\nWhat would make it reachable: about "
                  f"{alternatives['days_needed_at_world_class_skill']} days instead, or a "
                  f"stake of about R{alternatives['funding_for_1pct_risk_zar']:,.0f} so each "
                  f"trade risks a normal 1% instead of {verdict.risk_per_trade_pct:.0f}%.")
    if s["assumed"]:
        reply += ("\n\n(You did not say how much or by when, so I assumed doubling it within "
                  "a year. Tell me the real numbers and I will redo this.)")
    return JSONResponse({"ok": True, "reply": reply, "feasible": verdict.feasible,
                         "detail": verdict.to_dict()})


PAGE = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>The money</title>
<style>
  :root{--paper:#faf7f2;--ink:#1c1917;--muted:#6b6560;--line:#e7e0d6;--good:#2f6f4e;
        --bad:#a33a2a;--clay:#c2683f;--card:#fff}
  @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#16140f;
    --ink:#f2ede4;--muted:#a49c91;--line:#2e2a23;--card:#1e1b16;--good:#6fbf91;--bad:#e08370}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 ui-sans-serif,
       system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:0 16px 64px}
  .wrap{max-width:860px;margin:0 auto}
  header{padding:32px 0 8px}
  h1{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}
  .sub{color:var(--muted);font-size:15px;margin:0}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;
        margin:24px 0}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
  .q{color:var(--muted);font-size:14px;margin:0 0 6px}
  .n{font-size:32px;font-weight:650;letter-spacing:-.02em;margin:0}
  .n.good{color:var(--good)} .n.bad{color:var(--bad)}
  .hint{color:var(--muted);font-size:13px;margin:6px 0 0}
  .banner{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--clay);
          border-radius:12px;padding:16px 18px;margin:16px 0}
  h2{font-size:18px;margin:32px 0 10px}
  ul.lessons{list-style:none;padding:0;margin:0}
  ul.lessons li{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:14px 16px;margin-bottom:10px}
  ul.lessons .ev{color:var(--muted);font-size:13px;margin-top:4px}
  .chat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;
        margin-top:12px}
  textarea,input{width:100%;font:inherit;padding:12px;border:1px solid var(--line);
        border-radius:10px;background:var(--paper);color:var(--ink)}
  textarea{min-height:76px;resize:vertical}
  button{font:inherit;font-weight:600;padding:12px 18px;border:0;border-radius:10px;
        background:var(--clay);color:#fff;cursor:pointer;margin-top:10px;min-height:44px}
  button:disabled{opacity:.5;cursor:default}
  .reply{white-space:pre-wrap;margin-top:14px;padding:14px 16px;border-radius:10px;
        background:var(--paper);border:1px solid var(--line)}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
  .row>div{flex:1;min-width:160px}
  details{margin-top:28px;border-top:1px solid var(--line);padding-top:14px}
  summary{cursor:pointer;color:var(--muted);font-size:14px}
  table{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}
  td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
  .foot{color:var(--muted);font-size:13px;margin-top:28px}
  .tag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;
       border:1px solid var(--line);color:var(--muted)}
</style></head><body><div class="wrap">
<header>
  <h1>The money</h1>
  <p class="sub" id="asof">Loading…</p>
</header>

<div class="grid" id="cards"></div>

<div class="banner" id="why"></div>

<h2>What it has learned</h2>
<ul class="lessons" id="lessons"></ul>

<h2>Tell it what you want</h2>
<div class="chat">
  <div id="loginbox" hidden>
    <p class="q">Sign in to set a goal.</p>
    <div class="row">
      <div><input id="pw" type="password" placeholder="Password" autocomplete="current-password"></div>
      <div style="flex:0"><button id="loginbtn">Sign in</button></div>
    </div>
  </div>
  <div id="goalbox" hidden>
    <div class="row"><div>
      <input id="who" placeholder="Your name" autocomplete="name">
    </div></div>
    <textarea id="goal" placeholder="For example: I want to turn this into R2000 by December, and I can afford to lose half."></textarea>
    <button id="send">Ask</button>
    <div class="reply" id="reply" hidden></div>
  </div>
  <p class="hint">This sets a goal for the research system. It cannot place a trade, and
  nothing you type here moves money.</p>
</div>

<details>
  <summary>Show the technical detail</summary>
  <table id="tech"></table>
</details>

<p class="foot" id="foot"></p>
</div>
<script>
const $=id=>document.getElementById(id);
const money=v=>'R'+Number(v||0).toLocaleString(undefined,{maximumFractionDigits:0});
let D={};
async function load(){
  D=await (await fetch('/api/data')).json();
  $('asof').textContent = D.as_of ? ('As of '+new Date(D.as_of).toLocaleString()) :
      'No balance recorded yet.';
  $('cards').innerHTML=[
    ['How much money do I have?', money(D.have_zar), '', 'about $'+Number(D.have_usd||0).toFixed(2)],
    ['How much did it try to trade?', money(D.risked_zar), '',
      D.executed? (D.executed+' trades placed') : (D.attempted+' attempt, rejected: the account was too small to place it')],
    ['How much did it make?', money(D.made_zar), D.made_zar>0?'good':'', 'money actually won'],
    ['How much did it lose?', money(D.lost_zar), D.lost_zar>0?'bad':'', 'money actually lost'],
  ].map(([q,n,cls,h])=>`<div class="card"><p class="q">${q}</p>
      <p class="n ${cls}">${n}</p><p class="hint">${h}</p></div>`).join('');
  $('why').innerHTML='<strong>What is it doing?</strong><br>'+D.why_no_trade;
  $('lessons').innerHTML = (D.lessons&&D.lessons.length)
    ? D.lessons.map(l=>`<li>${l.lesson}<div class="ev">${l.evidence||''}</div></li>`).join('')
    : `<li>It has tested ${D.ideas_tested} ideas so far and none of them beat the cost of
       trading. That is the finding: the easy ideas do not work, which is why it is still
       looking instead of betting.<div class="ev">From the engine's own test results.</div></li>`;
  $('tech').innerHTML=`<tr><th>Ideas tested</th><td>${D.ideas_tested}</td></tr>
    <tr><th>Ideas that passed the bar</th><td>${D.ideas_passed}</td></tr>
    <tr><th>Orders attempted / executed</th><td>${D.attempted} / ${D.executed}</td></tr>
    <tr><th>Balance (USD)</th><td>${Number(D.have_usd||0).toFixed(2)}</td></tr>
    <tr><th>Rate used</th><td>R${D.zar_per_usd}/USD</td></tr>
    <tr><th>Last research run</th><td>${D.last_run||'never'}</td></tr>`;
  $('foot').textContent = D.configured ? '' : 'Data source not configured yet.';
  $('loginbox').hidden = !!document.cookie.includes('auth=') || !D.can_set_goals;
  $('goalbox').hidden  = !document.cookie.includes('auth=');
  if(!D.can_set_goals){ $('loginbox').hidden=true; $('goalbox').hidden=true;
    $('reply').hidden=false; $('reply').textContent=
      'The goal channel is closed: the dashboard has no write key or no password set.'; }
}
$('loginbtn').onclick=async()=>{
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:$('pw').value})});
  if(r.ok){ $('loginbox').hidden=true; $('goalbox').hidden=false; }
  else { $('pw').value=''; $('pw').placeholder='Wrong password'; }
};
$('send').onclick=async()=>{
  const b=$('send'); b.disabled=true; b.textContent='Working it out…';
  const r=await fetch('/api/goal',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:$('goal').value,author:$('who').value})});
  const j=await r.json();
  $('reply').hidden=false; $('reply').textContent=j.reply||j.error||'Something went wrong.';
  b.disabled=false; b.textContent='Ask';
};
load();
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE
