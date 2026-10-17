"""The live-money gate. Every test here is a refusal except one.

This is the only boundary the owner kept for himself when he granted the project full
autonomy, so the tests are written from the attacker's side: what would an agent that
wanted to trade actually try? Write the file itself, reorder the fields, extend its own
expiry, point it at a different account, raise its own ceiling. Each of those has a test.
"""
from __future__ import annotations

import json
import time

import pytest

from ops import authority as auth

SECRET = "owner-secret-not-present-in-dev"


@pytest.fixture(autouse=True)
def _no_standing_secret(tmp_path, monkeypatch):
    """Tests are about the gate, not this machine: never read the real standing secret."""
    monkeypatch.setattr(auth, "STANDING_SECRET_FILE", tmp_path / "no_standing_secret")


@pytest.fixture
def grant(tmp_path, monkeypatch):
    """A helper that writes a VALID grant, as only the owner could."""
    path = tmp_path / "live_authority.json"
    monkeypatch.setattr(auth, "AUTHORITY_FILE", path)

    def _write(account_id=12345678, max_capital_zar=5000.0, days=7, secret=SECRET,
               **overrides):
        now = time.time()
        payload = {"account_id": account_id, "max_capital_zar": max_capital_zar,
                   "granted_ts": now, "expires_ts": now + days * 86400.0, "note": ""}
        payload.update(overrides)
        payload["signature"] = auth._sign(payload, secret)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
    _write.path = path
    return _write


# ------------------------------------------------------------------ the default


def test_a_development_session_can_never_authorise_itself(monkeypatch):
    """The secret is absent here by design. That alone must end it."""
    monkeypatch.delenv(auth.SECRET_ENV, raising=False)
    a = auth.live_trading_permitted(12345678)
    assert a.permitted is False
    assert auth.SECRET_ENV in a.reason


def test_no_grant_file_means_no(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    monkeypatch.setattr(auth, "AUTHORITY_FILE", tmp_path / "absent.json")
    assert auth.live_trading_permitted(12345678).permitted is False


def test_the_real_environment_has_no_secret_variable():
    """The secret is never an environment variable here; standing authority uses a file."""
    import os
    assert not os.environ.get(auth.SECRET_ENV)


# ------------------------------------------------------------------ forgery


def test_an_unsigned_file_is_refused(tmp_path, monkeypatch):
    """The simplest attack: write the file and hope nobody checks the signature."""
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"account_id": 12345678, "max_capital_zar": 1e9,
                             "expires_ts": time.time() + 9e6}), encoding="utf-8")
    monkeypatch.setattr(auth, "AUTHORITY_FILE", p)
    a = auth.live_trading_permitted(12345678)
    assert a.permitted is False
    assert "no signature" in a.reason


def test_a_file_signed_with_the_wrong_secret_is_refused(grant, monkeypatch):
    """What an agent could actually produce: a well-formed grant signed with a guess."""
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    grant(secret="a-secret-the-agent-invented")
    a = auth.live_trading_permitted(12345678)
    assert a.permitted is False
    assert "does not verify" in a.reason


def test_tampering_with_any_signed_field_breaks_the_signature(grant, monkeypatch):
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    path = grant(max_capital_zar=100.0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["max_capital_zar"] = 1_000_000.0        # raise own ceiling, keep signature
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert auth.live_trading_permitted(12345678).permitted is False


def test_extending_your_own_expiry_breaks_the_signature(grant, monkeypatch):
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    path = grant(days=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["expires_ts"] = time.time() + 10 * 365 * 86400
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert auth.live_trading_permitted(12345678).permitted is False


def test_reordering_the_fields_does_not_change_the_signature(grant, monkeypatch):
    """Canonical ordering: a re-serialised file is still valid, so this is not a bypass."""
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    path = grant()
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(reversed(list(payload.items())))), encoding="utf-8")
    assert auth.live_trading_permitted(12345678).permitted is True


def test_an_unreadable_file_is_refused_not_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    p = tmp_path / "a.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(auth, "AUTHORITY_FILE", p)
    assert auth.live_trading_permitted(12345678).permitted is False


# ------------------------------------------------------------------ scope


def test_expired_authorisation_is_refused(grant, monkeypatch):
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    grant(days=-1)
    a = auth.live_trading_permitted(12345678)
    assert a.permitted is False
    assert "expired" in a.reason


def test_a_grant_for_one_account_does_not_cover_another(grant, monkeypatch):
    """The demo and live ids differ by one digit. This is exactly where a slip happens."""
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    grant(account_id=12345678)
    a = auth.live_trading_permitted(99999999)
    assert a.permitted is False
    assert "12345678" in a.reason


def test_capital_above_the_authorised_ceiling_is_refused(grant, monkeypatch):
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    grant(max_capital_zar=5000.0)
    assert auth.live_trading_permitted(12345678, capital_zar=5000.01).permitted is False
    assert auth.live_trading_permitted(12345678, capital_zar=4999.99).permitted is True


# ------------------------------------------------------------------ the one yes


def test_a_valid_owner_grant_is_permitted(grant, monkeypatch):
    """The gate must be able to open, or the owner could never trade at all."""
    monkeypatch.setenv(auth.SECRET_ENV, SECRET)
    grant()
    a = auth.live_trading_permitted(12345678, capital_zar=1000.0)
    assert a.permitted is True
    assert a.account_id == 12345678


def test_require_raises_rather_than_returning(monkeypatch, tmp_path):
    monkeypatch.delenv(auth.SECRET_ENV, raising=False)
    monkeypatch.setattr(auth, "AUTHORITY_FILE", tmp_path / "absent.json")
    with pytest.raises(PermissionError):
        auth.require_live_authority(12345678)


# ------------------------------------------------------------------ standing authority


def test_standing_secret_file_authorises_and_renews(tmp_path, monkeypatch):
    monkeypatch.delenv(auth.SECRET_ENV, raising=False)
    monkeypatch.setattr(auth, "AUTHORITY_FILE", tmp_path / "grant.json")
    (tmp_path / "no_standing_secret").write_text(SECRET, encoding="utf-8")
    now = time.time()
    a = auth.ensure_standing(12345678, now=now)
    assert a.permitted and a.max_capital_zar == auth.STANDING_CEILING_ZAR
    # Renewed once it is within a week of expiry, not before.
    first = json.loads((tmp_path / "grant.json").read_text())["granted_ts"]
    auth.ensure_standing(12345678, now=now + 86400)
    assert json.loads((tmp_path / "grant.json").read_text())["granted_ts"] == first
    later = now + (auth.MAX_GRANT_DAYS - 3) * 86400
    assert auth.ensure_standing(12345678, now=later).permitted
    assert json.loads((tmp_path / "grant.json").read_text())["granted_ts"] == later


def test_no_standing_secret_means_no_standing_grant(tmp_path, monkeypatch):
    monkeypatch.delenv(auth.SECRET_ENV, raising=False)
    monkeypatch.setattr(auth, "AUTHORITY_FILE", tmp_path / "grant.json")
    assert auth.ensure_standing(12345678).permitted is False
    assert not (tmp_path / "grant.json").exists()


def test_a_changed_ceiling_is_re_signed(tmp_path, monkeypatch):
    monkeypatch.delenv(auth.SECRET_ENV, raising=False)
    monkeypatch.setattr(auth, "AUTHORITY_FILE", tmp_path / "grant.json")
    (tmp_path / "no_standing_secret").write_text(SECRET, encoding="utf-8")
    assert auth.ensure_standing(12345678, max_capital_zar=600).max_capital_zar == 600
    assert auth.ensure_standing(12345678, max_capital_zar=2000).max_capital_zar == 2000
