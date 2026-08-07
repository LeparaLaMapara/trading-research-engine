"""The dashboard + chat front-end (Render free web service).

Shows the live account balance, every strategy the engine tried (with how much each would
have made/lost), the agent-calibration scoreboard, and what the Scout fetched. Includes a
chat panel (text + browser voice) to talk to the agents the way the owner talks to Claude.

Read-only over the data. The chat can explain and reason but CANNOT place trades — the risk
layer stays fail-closed and no order path is reachable from here.

Run local:  uvicorn dashboard.app:app --port 8080
Reads Supabase server-side with the service-role key (never exposed to the browser).
"""
from __future__ import annotations

import os

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from config import settings

app = FastAPI(title="Trading Research Engine")
CHAT_MODEL = os.environ.get("DASHBOARD_CHAT_MODEL", "claude-opus-5")


# ------------------------------------------------------------------ Supabase reads
def _sb_get(table: str, query: str = "") -> list[dict]:
    if not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
        return []
    try:
        r = requests.get(
            f"{settings.SUPABASE_URL}/rest/v1/{table}?{query}",
            headers={"apikey": settings.SUPABASE_KEY,
                     "Authorization": f"Bearer {settings.SUPABASE_KEY}"},
            timeout=15)
        return r.json() if r.status_code < 300 else []
    except Exception:  # noqa: BLE001
        return []


def _dashboard_data() -> dict:
    balance = _sb_get("trading_account", "select=balance,equity,currency,ts&order=ts.desc&limit=1")
    strategies = _sb_get(
        "trading_strategies",
        "select=run_ts,symbol,kind,source,verdict,dev_sharpe,holdout_sharpe,total_return,"
        "max_drawdown,dsr,pnl_on_10&order=run_ts.desc&limit=50")
    calibration = _sb_get("trading_calibration", "select=*&order=field_accuracy.desc")
    cards = _sb_get("trading_cards", "select=identifier,title,mapped_kind,url&order=created_ts.desc&limit=20")
    return {"balance": balance[0] if balance else None,
            "strategies": strategies, "calibration": calibration, "cards": cards,
            "configured": bool(settings.SUPABASE_URL and settings.SUPABASE_KEY)}


@app.get("/api/data")
def api_data() -> JSONResponse:
    return JSONResponse(_dashboard_data())


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ------------------------------------------------------------------ chat with the agents
def _engine_context(data: dict) -> str:
    bal = data.get("balance")
    parts = ["You are the assistant for a personal trading RESEARCH engine (LLMs propose, "
             "deterministic code decides; nothing trades live; the risk layer is fail-closed). "
             "You explain the data below and the methodology honestly. You CANNOT place, modify, "
             "or close trades, and must never claim to. Be concise and plain-spoken."]
    if bal:
        parts.append(f"Current account balance: {bal.get('balance')} {bal.get('currency','')}.")
    tested = [s for s in data.get("strategies", []) if s.get("verdict") in ("PASS", "FAIL")]
    if tested:
        parts.append("Recent strategies tried (kind, verdict, dev Sharpe, total return, $ on $10):")
        for s in tested[:12]:
            parts.append(f"  - {s['kind']} on {s['symbol']}: {s['verdict']}, "
                         f"Sharpe {s.get('dev_sharpe')}, return {s.get('total_return')}, "
                         f"${s.get('pnl_on_10')} on $10")
    else:
        parts.append("No strategies have passed yet; every one tried so far has failed the "
                     "deflated-Sharpe bar (this is the system being honest, not broken).")
    return "\n".join(parts)


@app.post("/api/chat")
def api_chat(payload: dict) -> JSONResponse:
    message = (payload or {}).get("message", "").strip()
    history = (payload or {}).get("history", [])
    if not message:
        return JSONResponse({"reply": "Ask me anything about the engine, the balance, or the "
                                      "strategies tried."})
    try:
        import anthropic
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env
        msgs = [{"role": m["role"], "content": m["content"]}
                for m in history if m.get("role") in ("user", "assistant")][-10:]
        msgs.append({"role": "user", "content": message})
        resp = client.messages.create(
            model=CHAT_MODEL, max_tokens=1024,
            system=_engine_context(_dashboard_data()), messages=msgs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return JSONResponse({"reply": text or "(no response)"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"reply": f"chat unavailable: {exc}"}, status_code=200)


# ------------------------------------------------------------------ the page
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Research Engine</title>
<style>
:root{--bg:#0e1116;--card:#171b22;--line:#252b34;--fg:#e6e9ee;--mut:#8b95a3;--good:#3fb950;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
h1{font-size:18px;margin:0}.mut{color:var(--mut)}
.wrap{display:grid;grid-template-columns:1fr 380px;gap:18px;padding:18px 22px;max-width:1400px}
@media(max-width:980px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:18px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 12px}
.bal{font-size:34px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600}.pos{color:var(--good)}.neg{color:var(--bad)}
.pill{font-size:11px;padding:2px 7px;border-radius:10px;border:1px solid var(--line)}
.PASS{color:var(--good);border-color:var(--good)}.FAIL{color:var(--bad)}.REJECTED,.SKIPPED{color:var(--mut)}
.scroll{max-height:360px;overflow:auto}
#chat{display:flex;flex-direction:column;height:calc(100vh - 130px);position:sticky;top:18px}
#log{flex:1;overflow:auto;display:flex;flex-direction:column;gap:10px;padding-right:4px}
.msg{padding:9px 12px;border-radius:10px;max-width:92%}
.u{align-self:flex-end;background:#1f2733}.a{align-self:flex-start;background:#12161c;border:1px solid var(--line)}
.row{display:flex;gap:8px;margin-top:10px}input,button{font:inherit}
input{flex:1;background:#0b0e13;border:1px solid var(--line);color:var(--fg);border-radius:9px;padding:10px}
button{background:var(--acc);color:#04121f;border:0;border-radius:9px;padding:0 14px;cursor:pointer;font-weight:600}
button.ghost{background:#0b0e13;color:var(--fg);border:1px solid var(--line)}
a{color:var(--acc);text-decoration:none}
.note{background:#2a2213;border:1px solid #6b5619;color:#e3c778;padding:10px 12px;border-radius:9px;margin:0 22px}
</style></head><body>
<header><h1>Trading Research Engine</h1><span class="mut">LLMs propose, code decides. Nothing trades live.</span></header>
<div id="cfg"></div>
<div class="wrap">
  <div>
    <div class="card"><h2>Account balance</h2><div class="bal" id="bal">—</div><div class="mut" id="balts"></div></div>
    <div class="card"><h2>Strategies tried &middot; how much each would have made/lost (on $10)</h2>
      <div class="scroll"><table id="strat"><thead><tr>
        <th>kind</th><th>sym</th><th>src</th><th>verdict</th><th>Sharpe</th><th>holdout</th><th>DSR</th><th>maxDD</th><th>$ / $10</th>
      </tr></thead><tbody></tbody></table></div></div>
    <div class="card"><h2>Agent calibration (are their confident predictions right?)</h2>
      <table id="cal"><thead><tr><th>agent</th><th>predictions</th><th>field accuracy</th><th>confidence</th></tr></thead><tbody></tbody></table></div>
    <div class="card"><h2>Scout finds (real papers fetched)</h2><div class="scroll"><table id="cards"><thead><tr><th>paper</th><th>maps to</th></tr></thead><tbody></tbody></table></div></div>
  </div>
  <div class="card" id="chat"><h2>Chat with the agents</h2>
    <div id="log"><div class="msg a">Hi. Ask about the balance, which strategies were tried, or how the engine works. Tap the mic to talk.</div></div>
    <div class="row"><input id="in" placeholder="Ask the agents..." autocomplete="off">
      <button class="ghost" id="mic" title="voice">&#127908;</button><button id="send">Send</button></div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s);
function money(x){return (x>=0?'+':'')+x.toFixed(2)}
async function load(){
  const d=await (await fetch('/api/data')).json();
  if(!d.configured){document.getElementById('cfg').innerHTML='<div class="note">Supabase not configured yet (set SUPABASE_URL and SUPABASE_KEY). Showing empty data; chat still works.</div>'}
  if(d.balance){$('#bal').textContent=(d.balance.balance??'—')+' '+(d.balance.currency||'');$('#balts').textContent='as of '+(d.balance.ts||'').replace('T',' ').slice(0,16)}
  const sb=$('#strat tbody');sb.innerHTML='';
  (d.strategies||[]).forEach(s=>{const pnl=s.pnl_on_10??0;const tr=document.createElement('tr');
    tr.innerHTML=`<td>${s.kind}</td><td>${s.symbol}</td><td>${s.source||''}</td>
    <td><span class="pill ${s.verdict}">${s.verdict||''}</span></td>
    <td>${s.dev_sharpe??''}</td><td>${s.holdout_sharpe??''}</td><td>${(s.dsr??0).toFixed?.(2)??s.dsr??''}</td>
    <td>${s.max_drawdown!=null?(s.max_drawdown*100).toFixed(0)+'%':''}</td>
    <td class="${pnl>=0?'pos':'neg'}">${s.pnl_on_10!=null?money(pnl):''}</td>`;sb.appendChild(tr)});
  const cb=$('#cal tbody');cb.innerHTML='';
  (d.calibration||[]).forEach(c=>{const tr=document.createElement('tr');
    tr.innerHTML=`<td>${c.agent}</td><td>${c.n_predictions??''}</td><td>${(c.field_accuracy??0).toFixed?.(2)??''}</td><td>${(c.mean_confidence??0).toFixed?.(2)??''}</td>`;cb.appendChild(tr)});
  const kb=$('#cards tbody');kb.innerHTML='';
  (d.cards||[]).forEach(k=>{const tr=document.createElement('tr');
    tr.innerHTML=`<td><a href="${k.url||'#'}" target="_blank">${(k.title||k.identifier||'').slice(0,60)}</a></td><td>${k.mapped_kind||'—'}</td>`;kb.appendChild(tr)});
}
load();setInterval(load,60000);
// chat
const hist=[];
function add(role,txt){const d=document.createElement('div');d.className='msg '+(role==='user'?'u':'a');d.textContent=txt;$('#log').appendChild(d);$('#log').scrollTop=1e9;return d}
async function send(){const t=$('#in').value.trim();if(!t)return;$('#in').value='';add('user',t);hist.push({role:'user',content:t});
  const ph=add('assistant','...');
  try{const r=await (await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t,history:hist})})).json();
    ph.textContent=r.reply;hist.push({role:'assistant',content:r.reply});speak(r.reply);}catch(e){ph.textContent='error: '+e}}
$('#send').onclick=send;$('#in').addEventListener('keydown',e=>{if(e.key==='Enter')send()});
// voice out
function speak(t){try{const u=new SpeechSynthesisUtterance(t);speechSynthesis.cancel();speechSynthesis.speak(u)}catch(e){}}
// voice in
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;let rec=null;
if(SR){rec=new SR();rec.lang='en-US';rec.interimResults=false;
  rec.onresult=e=>{$('#in').value=e.results[0][0].transcript;send()};
  $('#mic').onclick=()=>{try{rec.start()}catch(e){}}}
else{$('#mic').style.display='none'}
</script></body></html>"""
