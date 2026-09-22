"""The one gate that an autonomous agent must not be able to open by itself.

On 2026-09-16 the owner granted this project full autonomy with a single exception, in his
own words: the only pause is when dealing with the money in the live account. Everything
else, including changing permissions and spawning agents, proceeds without asking.

That is a workable boundary only if it survives the thing it is protecting against. A rule
that lives in a chat log is one context window from gone, and an agent that has been told
"you may edit any file" can edit the file that says it may not trade. So the boundary is
enforced here, and it is built to resist the agent itself.

**The mechanism.** Live trading requires an authorisation file whose contents are signed
with `LIVE_AUTHORITY_SECRET` using HMAC-SHA256. That secret is set by the owner in the
live-trading environment ONLY. It is deliberately absent from the development session, so
an agent working here can write the file, can edit this module, can grant itself every
permission in the repository, and still cannot produce a valid signature. Forging one
requires a secret it has never been given.

**What this does NOT guarantee, stated plainly.** It is a control, not a proof. An agent
with filesystem access can delete this check from the code path that calls it. What the
design buys is that doing so is a visible, reviewable change to a named module, caught by
`ops/audit.py`, rather than a silent drift in behaviour. Combined with `risk/limits.py`
denying whenever `LIVE_LIMITS` is unconfigured, live money has two independent locks that
both have to be picked deliberately. The honest claim is: no accident and no drift gets
through, and a deliberate bypass leaves evidence.

**Reading the broker is not trading.** Bars, symbol specs, account balance, margin quotes
and reconciliation are reads. They move no money and are not gated here. This module gates
exactly one thing: sending an order that can change a live balance.

**Standing authority, from 2026-09-23.** The owner then told the project, in his words: "I
don't want it to ask me anymore ... the objective is to get better, learn as much as you can
and start beating the market", accepting losses. So the secret may also live in
`STANDING_SECRET_FILE`, outside the repo on this machine, where the engine loop reads it and
renews its own grant (`ensure_standing`). What still binds every live order: the signed
LIVE_LIMITS in risk/limits.py (6% risk per trade, 2 positions, a permanent stop at $20
equity), the capital ceiling in the grant, and the audit, which fails if either drifts. To end
standing authority: delete the secret file and run `python -m ops.authority --revoke`.

To authorise live trading the owner runs, in the live environment only:

    python -m ops.authority --grant --account 46748922 --max-capital-zar 5000

with `LIVE_AUTHORITY_SECRET` set in that shell. Nothing else creates a valid grant.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

#: Where the signed grant lives. Outside the repo on purpose: a file inside the working
#: tree is one `git checkout` from reappearing, and one careless commit from being public.
AUTHORITY_FILE = Path(os.environ.get(
    "LIVE_AUTHORITY_FILE",
    str(Path.home() / ".trading-research-engine" / "live_authority.json")))

#: Set by the OWNER, in the live environment only. Never in a development session.
SECRET_ENV = "LIVE_AUTHORITY_SECRET"

#: Standing authority (owner decision 2026-09-23): the same secret, kept on this machine
#: outside the repo, so the engine loop can trade and renew without asking.
STANDING_SECRET_FILE = Path(os.environ.get(
    "LIVE_STANDING_SECRET_FILE",
    str(Path.home() / ".trading-research-engine" / "live_secret")))
STANDING_CEILING_ZAR = 600.0
RENEW_BELOW_DAYS = 7

#: A grant expires. An authorisation given once for one test must not still be open months
#: later when nobody remembers granting it.
MAX_GRANT_DAYS = 30

_SIGNED_FIELDS = ("account_id", "max_capital_zar", "granted_ts", "expires_ts", "note")


@dataclass(frozen=True)
class Authority:
    permitted: bool
    reason: str
    account_id: int | None = None
    max_capital_zar: float | None = None
    expires_ts: float | None = None

    def to_dict(self) -> dict:
        return {"permitted": self.permitted, "reason": self.reason,
                "account_id": self.account_id, "max_capital_zar": self.max_capital_zar,
                "expires_ts": self.expires_ts}


def _sign(payload: dict, secret: str) -> str:
    """HMAC over the signed fields only, canonically ordered so it cannot be reordered."""
    body = json.dumps({k: payload.get(k) for k in _SIGNED_FIELDS},
                      sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _secret() -> str:
    """The environment variable, else the standing secret file. Empty when neither exists."""
    env = os.environ.get(SECRET_ENV, "")
    if env:
        return env
    try:
        return STANDING_SECRET_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_standing(account_id: int, max_capital_zar: float = STANDING_CEILING_ZAR,
                    days: int = MAX_GRANT_DAYS, now: float | None = None) -> Authority:
    """Keep the standing grant alive: sign a fresh one when missing or within
    RENEW_BELOW_DAYS of expiry. Only works where the standing secret file exists."""
    now = time.time() if now is None else now
    secret = _secret()
    if not secret:
        return Authority(False, "no standing secret on this machine")
    cur = live_trading_permitted(account_id, now=now)
    if cur.permitted and (cur.expires_ts or 0) - now > RENEW_BELOW_DAYS * 86400:
        return cur
    payload = {"account_id": int(account_id), "max_capital_zar": float(max_capital_zar),
               "granted_ts": now, "expires_ts": now + days * 86400.0,
               "note": "standing authority, owner instruction 2026-09-23 (engine renews)"}
    payload["signature"] = _sign(payload, secret)
    AUTHORITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTHORITY_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return live_trading_permitted(account_id, now=now)


def live_trading_permitted(account_id: int | None = None,
                           capital_zar: float | None = None,
                           now: float | None = None) -> Authority:
    """May this process send an order that moves real money? Default: no.

    Every failure path returns a refusal. There is no branch that returns permitted on
    missing information, because "I could not tell" and "yes" must never be the same
    answer where live money is concerned.
    """
    now = time.time() if now is None else now

    secret = _secret()
    if not secret:
        return Authority(False, f"{SECRET_ENV} is not set in this environment and there is "
                                f"no standing secret on this machine, so it cannot "
                                f"authorise live trading.")

    if not AUTHORITY_FILE.exists():
        return Authority(False, f"no authorisation grant at {AUTHORITY_FILE}")

    try:
        payload = json.loads(AUTHORITY_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return Authority(False, f"authorisation file is unreadable: {type(exc).__name__}")

    signature = payload.get("signature")
    if not signature:
        return Authority(False, "authorisation file carries no signature")
    if not hmac.compare_digest(_sign(payload, secret), str(signature)):
        return Authority(False, "authorisation signature does not verify. The file was not "
                                "produced by the owner with the live secret, so it is "
                                "refused whatever it claims.")

    expires = float(payload.get("expires_ts") or 0)
    if now > expires:
        return Authority(False, f"authorisation expired "
                                f"{time.strftime('%Y-%m-%d', time.gmtime(expires))}",
                         expires_ts=expires)

    granted_account = payload.get("account_id")
    if account_id is not None and int(granted_account or 0) != int(account_id):
        return Authority(False, f"authorisation is for account {granted_account}, not "
                                f"{account_id}")

    cap = float(payload.get("max_capital_zar") or 0)
    if capital_zar is not None and capital_zar > cap:
        return Authority(False, f"this would put R{capital_zar:,.2f} at risk, above the "
                                f"authorised ceiling of R{cap:,.2f}",
                         account_id=granted_account, max_capital_zar=cap)

    return Authority(True, "owner-signed authorisation is valid",
                     account_id=int(granted_account), max_capital_zar=cap,
                     expires_ts=expires)


def require_live_authority(account_id: int | None = None,
                           capital_zar: float | None = None) -> Authority:
    """Same check, but raises. For call sites where proceeding unauthorised is unthinkable."""
    a = live_trading_permitted(account_id, capital_zar)
    if not a.permitted:
        raise PermissionError(f"live trading refused: {a.reason}")
    return a


def _grant(account_id: int, max_capital_zar: float, days: int, note: str) -> int:
    secret = _secret()
    if not secret:
        print(f"{SECRET_ENV} is not set. Set it in the live environment and run this "
              f"there.\nA grant signed without it would not verify, so none was written.",
              file=sys.stderr)
        return 2
    if days > MAX_GRANT_DAYS:
        print(f"maximum grant is {MAX_GRANT_DAYS} days.", file=sys.stderr)
        return 2
    now = time.time()
    payload = {"account_id": int(account_id), "max_capital_zar": float(max_capital_zar),
               "granted_ts": now, "expires_ts": now + days * 86400.0, "note": note}
    payload["signature"] = _sign(payload, secret)
    AUTHORITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTHORITY_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"granted: account {account_id}, ceiling R{max_capital_zar:,.2f}, "
          f"expires in {days} days\nwritten to {AUTHORITY_FILE}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Live-trading authorisation. Owner only.")
    p.add_argument("--grant", action="store_true")
    p.add_argument("--revoke", action="store_true")
    p.add_argument("--account", type=int)
    p.add_argument("--max-capital-zar", type=float)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--note", default="")
    a = p.parse_args()

    if a.revoke:
        if AUTHORITY_FILE.exists():
            AUTHORITY_FILE.unlink()
            print(f"revoked: removed {AUTHORITY_FILE}")
        else:
            print("nothing to revoke")
        return 0
    if a.grant:
        if not a.account or a.max_capital_zar is None:
            print("--grant needs --account and --max-capital-zar", file=sys.stderr)
            return 2
        return _grant(a.account, a.max_capital_zar, a.days, a.note)

    status = live_trading_permitted()
    print(f"live trading permitted: {status.permitted}\n  {status.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
