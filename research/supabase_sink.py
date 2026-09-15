"""Push experiment results to Supabase so the dashboard can read them.

Server-side only (uses the service-role key). A no-op when SUPABASE_URL / SUPABASE_KEY are
unset, so local runs and CI without the key just skip it silently. Writes are the engine's
honest record: every strategy tried, its per-strategy P&L/drawdown, the calibration
scoreboard, and the papers the Scout fetched.
"""
from __future__ import annotations

import requests

from config import settings


def enabled() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_KEY)


def _headers(upsert: bool = False, write: bool = True) -> dict:
    h = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "Content-Type": "application/json",
        # Target this project's own schema. Without these the request hits `public`, where
        # these tables no longer live.
        "Content-Profile" if write else "Accept-Profile": settings.SUPABASE_SCHEMA,
    }
    if upsert:
        h["Prefer"] = "resolution=merge-duplicates"
    return h


def _post(table: str, rows: list[dict], upsert: bool = False) -> None:
    if not rows:
        return
    try:
        r = requests.post(f"{settings.SUPABASE_URL}/rest/v1/{table}",
                          headers=_headers(upsert), json=rows, timeout=30)
        if r.status_code >= 300:
            print(f"supabase {table} write failed: {r.status_code} {r.text[:160]}")
    except Exception as exc:  # noqa: BLE001
        print(f"supabase {table} error: {exc}")


def _strategy_row(t: dict, symbol: str, period: str) -> dict:
    p = t["proposal"]
    w = t.get("wf")
    summ = w["dev_summary"] if w else {}
    hold = (w or {}).get("holdout_summary") or {}
    total_return = summ.get("total_return", 0.0)
    return {
        "symbol": symbol, "period": period, "kind": p.kind, "params": p.params,
        "source": ("scout" if str(p.agent).startswith("scout") else "council"),
        "agent": p.agent,
        "dev_sharpe": summ.get("sharpe"), "holdout_sharpe": hold.get("sharpe"),
        "total_return": total_return, "max_drawdown": summ.get("max_drawdown"),
        "dsr": t.get("dsr"), "verdict": t.get("verdict"),
        "pnl_on_10": round(total_return * 10, 4),
        "pnl_on_200": round(total_return * 200, 4),
    }


def push_experiment(res: dict) -> None:
    """Write one experiment's strategies + calibration to Supabase (if configured)."""
    if not enabled():
        return
    symbol, period = res["symbol"], res["period"]
    rows = [_strategy_row(t, symbol, period) for t in res.get("tested", [])]
    # Rejected / skipped proposals carry no backtest, but are still worth recording.
    for t in res.get("trials", []):
        if t.get("verdict") in ("REJECTED", "SKIPPED"):
            p = t["proposal"]
            rows.append({"symbol": symbol, "period": period, "kind": p.kind,
                         "params": getattr(p, "params", {}),
                         "source": "scout" if str(p.agent).startswith("scout") else "council",
                         "agent": p.agent, "verdict": t["verdict"]})
    _post("trading_strategies", rows)

    calib = res.get("calibration")
    if calib is not None:
        crows = []
        for agent in sorted({t["proposal"].agent for t in res.get("tested", [])}):
            c = calib.agent_calibration(agent)
            crows.append({"agent": agent, "n_predictions": c.get("n_predictions", 0),
                          "field_accuracy": c.get("field_accuracy", 0.0),
                          "mean_confidence": c.get("mean_confidence", 0.0)})
        _post("trading_calibration", crows, upsert=True)


def push_account(balance: float, equity: float, currency: str, account_id: str) -> None:
    if not enabled():
        return
    _post("trading_account", [{"balance": balance, "equity": equity,
                               "currency": currency, "account_id": account_id}])


def push_cards(cards: list[dict]) -> None:
    if not enabled() or not cards:
        return
    rows = [{"identifier": c["identifier"], "title": c.get("title"),
             "discipline": c.get("discipline"), "url": c.get("url"),
             "market_claim": c.get("market_claim"), "mapped_kind": c.get("mapped_kind")}
            for c in cards if c.get("identifier") and c["identifier"] != "MOCK-OFFLINE"]
    _post("trading_cards", rows, upsert=True)
