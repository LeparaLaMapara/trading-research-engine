"""cTrader token access for the research engine.

Reuses the token store written by ctrader-connect's OAuth flow (TOKEN_STORE points at
its tokens.json), or an env-var seed. Load-focused; includes a refresh path so a
long-running telemetry logger can recover from a mid-run access-token expiry.

Never commit tokens.json or .env.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from config import settings

TOKEN_URL = "https://openapi.ctrader.com/apps/token"


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    """The token endpoint has used both camelCase and snake_case. Accept either."""
    def pick(*names: str) -> Any:
        for n in names:
            if payload.get(n) is not None:
                return payload[n]
        return None

    error = pick("errorCode", "error")
    if error:
        raise RuntimeError(f"token endpoint error: {error}: {pick('description', 'error_description')}")
    tokens = {
        "access_token": pick("accessToken", "access_token"),
        "refresh_token": pick("refreshToken", "refresh_token"),
        "expires_in": pick("expiresIn", "expires_in"),
        "token_type": pick("tokenType", "token_type") or "Bearer",
        "obtained_at": int(time.time()),
    }
    if not tokens["access_token"]:
        raise RuntimeError(f"token response had no access token: {payload}")
    return tokens


_REMOTE_TABLE = "ctrader_tokens"
_REMOTE_ROW = "default"


def _remote_headers(write: bool) -> dict[str, str]:
    return {"apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_KEY}",
            "Content-Type": "application/json",
            ("Content-Profile" if write else "Accept-Profile"): settings.SUPABASE_SCHEMA}


def _remote_load() -> dict[str, Any]:
    """The shared token store the hosted OAuth service writes to."""
    if not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
        return {}
    try:
        import requests
        r = requests.get(f"{settings.SUPABASE_URL}/rest/v1/{_REMOTE_TABLE}",
                         params={"id": f"eq.{_REMOTE_ROW}", "select": "*"},
                         headers=_remote_headers(False), timeout=20)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else {}
    except Exception:
        return {}


def _remote_save(tokens: dict[str, Any]) -> None:
    if not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
        return
    try:
        import requests
        requests.post(f"{settings.SUPABASE_URL}/rest/v1/{_REMOTE_TABLE}",
                      headers={**_remote_headers(True),
                               "Prefer": "resolution=merge-duplicates"},
                      json=[{"id": _REMOTE_ROW,
                             "access_token": tokens.get("access_token"),
                             "refresh_token": tokens.get("refresh_token"),
                             "token_type": tokens.get("token_type"),
                             "expires_in": tokens.get("expires_in"),
                             "obtained_at": tokens.get("obtained_at")}],
                      timeout=20).raise_for_status()
    except Exception:
        pass


def _obtained(t: dict[str, Any]) -> float:
    try:
        return float(t.get("obtained_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def load() -> dict[str, Any]:
    """File, then the shared store, then the env-var seed.

    The env seed is LAST on purpose. It used to be the fallback right after the file, and
    because the repo secrets went stale in August the daily run spent five weeks
    authenticating with a token the broker had already rejected -- while reporting success.
    The shared store is written by the hosted OAuth service, so a re-authorisation anywhere
    fixes every consumer at once, with nothing to paste.
    """
    store = settings.TOKEN_STORE
    local: dict[str, Any] = {}
    if store and os.path.exists(store):
        with open(store) as f:
            local = json.load(f)
    remote = _remote_load()
    # The PC and CI share one token lineage, and a refresh on either side kills the other's
    # copy. Whoever refreshed last wrote the shared store too, so take the NEWER of the two.
    # (Until 2026-10-21 the file always won, and a stale cached file failed CI for 3 days.)
    if local.get("access_token") and remote.get("access_token"):
        newer_remote = _obtained(remote) > _obtained(local)
        return remote if newer_remote else local
    if local.get("access_token"):
        return local
    if remote.get("access_token"):
        return remote
    seed_access = os.environ.get("CTRADER_ACCESS_TOKEN")
    seed_refresh = os.environ.get("CTRADER_REFRESH_TOKEN")
    if seed_access or seed_refresh:
        return {"access_token": seed_access, "refresh_token": seed_refresh}
    return {}


def save(tokens: dict[str, Any]) -> None:
    # Write both: the local file for speed, the shared store so a refresh here does not
    # leave the hosted service and CI holding the superseded token.
    store = settings.TOKEN_STORE
    if store:
        with open(store, "w") as f:
            json.dump(tokens, f, indent=2)
    _remote_save(tokens)


def refresh(refresh_token: str | None = None) -> dict[str, Any]:
    if refresh_token is None:
        refresh_token = load().get("refresh_token")
    if not refresh_token:
        raise RuntimeError("no refresh token available; re-run the ctrader-connect OAuth flow.")
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.CLIENT_ID,
        "client_secret": settings.CLIENT_SECRET,
    }, timeout=30)
    resp.raise_for_status()
    tokens = _normalise(resp.json())
    if not tokens.get("refresh_token"):
        tokens["refresh_token"] = refresh_token
    save(tokens)
    return tokens


def access_token() -> str | None:
    return load().get("access_token")
