"""The vault: the latest years, locked away from every search and opened once per experiment.

A search may look at the search room as often as it likes; that only costs N. The vault is the
checker. Each opening appends one line to an append-only log (experiment, time, the SHA-256 of
the short list it was opened for). A second opening for the same experiment is refused, so a
search cannot quietly try short list after short list against the vault until one passes.

    from research import vault
    mask = vault.open_once("E13", shortlist, days)       # boolean mask of vault days
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import pandas as pd

LOG = "docs/results/vault-log.jsonl"
#: inclusive bounds of the vault, by the trading day's closing date
VAULT = ("2023-01-01", "2026-09-30")
SEARCH = ("2014-01-01", "2022-12-31")


class VaultAlreadyOpened(RuntimeError):
    pass


def digest(shortlist) -> str:
    return hashlib.sha256(json.dumps(shortlist, sort_keys=True, default=str).encode()).hexdigest()


def openings(log: str = LOG) -> list[dict]:
    if not os.path.exists(log):
        return []
    with open(log, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def search_mask(days: pd.DatetimeIndex) -> "pd.Series":
    return (days >= SEARCH[0]) & (days <= SEARCH[1])


def open_once(experiment: str, shortlist, days: pd.DatetimeIndex, log: str = LOG):
    """Log the opening, then return the boolean mask of vault days. Refuses a second opening."""
    if not shortlist:
        raise ValueError("the vault opens only for a non-empty short list")
    if any(o["experiment"] == experiment for o in openings(log)):
        raise VaultAlreadyOpened(f"{experiment} has already opened the vault; see {log}")
    os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"experiment": experiment,
                             "opened": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "shortlist_sha256": digest(shortlist),
                             "n_rules": len(shortlist), "vault": list(VAULT)}) + "\n")
    return (days >= VAULT[0]) & (days <= VAULT[1])
