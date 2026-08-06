"""Send reports by email over SMTP, so the engine can deliver them itself.

Credentials come from the environment (never code, never git):
    SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 465, SSL)
    SMTP_USER, SMTP_PASS   -- for Gmail this MUST be a 16-char App Password, not the
                              account password (Google blocks plain-password SMTP).
    EMAIL_FROM (defaults to SMTP_USER), EMAIL_TO (comma-separated default recipients)

Usage:
    from report import mailer
    mailer.send("subject", plain_text, html_body, to=["a@x.com", "b@y.com"])
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from config import settings


def _recipients(to: list[str] | None) -> list[str]:
    if to:
        return to
    return [a.strip() for a in settings.EMAIL_TO.split(",") if a.strip()]


def is_configured() -> bool:
    return bool(settings.SMTP_USER and settings.SMTP_PASS)


def send(subject: str, plain: str, html: str | None = None,
         to: list[str] | None = None) -> None:
    if not is_configured():
        raise RuntimeError(
            "SMTP not configured. Set SMTP_USER and SMTP_PASS (a Gmail App Password) in .env.")
    recipients = _recipients(to)
    if not recipients:
        raise RuntimeError("no recipients. Pass to=[...] or set EMAIL_TO in .env.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM or settings.SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg.set_content(plain)
    if html:
        msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT) as s:
        s.login(settings.SMTP_USER, settings.SMTP_PASS)
        s.send_message(msg)
    print(f"email sent to {', '.join(recipients)}")
