"""IBKR micro futures: round-trip cost in bps and notional per contract, for VENUES.md.

Fees and contract specs are cited in docs/research-loop/VENUES.md section 2 (read 2026-11-20).
The reference price is the last close before the holdout start of the matching Dukascopy spot
series (pre-holdout data only; no strategy is run, no trials spent). Spread is ASSUMED 1 tick
for every contract (cited only for MES), so treat the result as a floor-ish estimate.

Run: PYTHONPATH=. ARTIFACT_ROOT=/mnt/t/making-money python lab/venues/futures_costs.py
"""
import json
import os

os.environ.setdefault("ARTIFACT_ROOT", "/mnt/t/making-money")
from scripts import long_history as L
from zoo.panel import build_panel

OUT = "docs/results/venues-futures-costs-2026-11-20.json"
IBKR_COMMISSION = 0.25          # per side, micro group, <=1,000 contracts a month
REG = 0.01 + 0.01               # CME regulatory recovery + NFA assessment, per side
# contract: (spot proxy, multiplier in quote units per point, tick size, exchange fee per side)
SPECS = {
    "MES": ("US500", 5.0, 0.25, 0.35),
    "MNQ": ("USTEC", 2.0, 0.25, 0.35),
    "MYM": ("US30", 0.5, 1.0, 0.35),
    "MGC": ("XAUUSD", 10.0, 0.10, 0.70),
    "SIL": ("XAGUSD", 1000.0, 0.005, None),   # exchange fee UNVERIFIED
    "MCL": ("XTIUSD", 100.0, 0.01, 0.50),
    "M6E": ("EURUSD", 12500.0, 0.0001, 0.24),
    "M6A": ("AUDUSD", 10000.0, 0.0001, None),  # fee UNVERIFIED (likely 0.24)
    "M6B": ("GBPUSD", 6250.0, 0.0001, None),   # fee UNVERIFIED (likely 0.24)
}

paths = {k: v for k, v in L.files().items() if k in {s[0] for s in SPECS.values()}}
p = build_panel(sorted(paths), loader=L.loader_for(paths))
p = p[p.date < L.HOLDOUT_START]
last = p.sort_values("date").groupby("symbol").last()

rows = {}
for c, (sym, mult, tick, exch) in SPECS.items():
    px = float(last.loc[sym, "close"])
    notional = px * mult
    fee_side = IBKR_COMMISSION + REG + (exch if exch is not None else 0.24)
    rt = 2 * fee_side + tick * mult           # fees both sides + one tick of spread
    rows[c] = {"proxy": sym, "ref_date": str(last.loc[sym, "date"].date()), "ref_price": px,
               "notional_usd": round(notional), "fees_round_trip_usd": round(2 * fee_side, 2),
               "spread_1tick_usd": round(tick * mult, 3), "round_trip_usd": round(rt, 2),
               "round_trip_bps": round(rt / notional * 1e4, 2),
               "fee_verified": exch is not None}
    print(f"{c:4} {sym:7} px {px:>10.4f} notional ${notional:>9,.0f} round trip ${rt:5.2f} "
          f"= {rt / notional * 1e4:5.2f} bps{'' if exch is not None else '  (fee assumed)'}")
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(rows, fh, indent=1)
print("wrote", OUT)
