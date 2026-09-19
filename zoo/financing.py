"""Overnight financing, split into the broker's FEE and the rate differential.

A swap quote has two parts. For a long:  swap_long  = differential - fee
                             for a short: swap_short = -differential - fee
so   fee          = -(swap_long + swap_short) / 2    (the broker's cut, charged both ways)
     differential =  (swap_long - swap_short) / 2    (what the position earns as carry)

The fee is a near-constant broker term, so measuring it today and applying it historically is
defensible. The differential tracks interest rates and must NOT be applied historically from
today's quote: for FX it comes from point-in-time rates (scripts/carry.py); for everything
else the evaluation works on EXCESS returns, where the differential is the cash rate an
unlevered holder would have earned anyway.

Quote conventions (cTrader): swapCalculationType 0 = pips per lot per day, 1 = annual percent.
Pips convert with pip = 10**-pipPosition, at the current price. Triple rollover means seven
charges per five trading days, so a daily charge annualises over 365 calendar days.
"""
from __future__ import annotations

import json


def annual_rates(spec: dict, price: float) -> tuple[float, float]:
    """(long, short) annual financing as a fraction of notional; negative = you pay."""
    L, S = float(spec.get("swapLong", 0.0)), float(spec.get("swapShort", 0.0))
    if int(spec.get("swapCalculationType", 0)) == 1:
        return L / 100.0, S / 100.0
    pip = 10.0 ** -int(spec["pipPosition"])
    return L * pip * 365.0 / price, S * pip * 365.0 / price


def fee_and_differential(spec: dict, price: float) -> tuple[float, float]:
    L, S = annual_rates(spec, price)
    return -(L + S) / 2.0, (L - S) / 2.0


def load(path: str = "data/swaps.json") -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
