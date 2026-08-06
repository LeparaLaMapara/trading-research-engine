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


def load() -> dict[str, Any]:
    """File first; fall back to env-var seed."""
    store = settings.TOKEN_STORE
    if store and os.path.exists(store):
        with open(store) as f:
            return json.load(f)
    seed_access = os.environ.get("CTRADER_ACCESS_TOKEN")
    seed_refresh = os.environ.get("CTRADER_REFRESH_TOKEN")
    if seed_access or seed_refresh:
        return {"access_token": seed_access, "refresh_token": seed_refresh}
    return {}


def save(tokens: dict[str, Any]) -> None:
    store = settings.TOKEN_STORE
    if not store:
        return
    with open(store, "w") as f:
        json.dump(tokens, f, indent=2)


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
