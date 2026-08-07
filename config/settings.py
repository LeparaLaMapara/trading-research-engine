"""Central configuration. Loads .env once, exposes typed settings. No secrets in code."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # reads .env in the repo root if present; real values never committed

CLIENT_ID = os.environ.get("CTRADER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CTRADER_CLIENT_SECRET", "")
ENV = os.environ.get("CTRADER_ENV", "demo").lower()          # demo | live
ACCOUNT_ID = os.environ.get("CTRADER_ACCOUNT_ID")            # ctidTraderAccountId
TOKEN_STORE = os.environ.get("TOKEN_STORE", "tokens.json")
TELEMETRY_DB = os.environ.get("TELEMETRY_DB", "data/telemetry.db")
LATENCY_INTERVAL_S = int(os.environ.get("LATENCY_INTERVAL_S", "30"))

SAST = "Africa/Johannesburg"

# Supabase (shared store for the dashboard). Server-side only: use the service-role key.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Email delivery (SMTP). For Gmail, SMTP_PASS must be a 16-char App Password.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "") or SMTP_USER
EMAIL_TO = os.environ.get("EMAIL_TO", "")     # comma-separated default recipients
