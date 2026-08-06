"""The 20/80 realised-profit ratchet (owner's rule), as a first-class ledger.

On each CLOSED, REALISED profit:
  * 80% is swept OUT of the trading pool and is never at risk again.
  * 20% is returned to the pool.
Losses reduce the pool and are never swept. "Profit" is realised P&L only — never
floating/unrealised. A hard STAKE FLOOR stops the system entirely if the pool falls
below it. A tax-provision line accrues against realised profit (SARS: active forex is
ordinary income, up to 45%); the swept 80% is pre-tax. Kept separate from broker
equity, which does not reflect the sweep.

Pure, deterministic, unit-tested. No AI, no broker calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SweepState:
    pool: float                     # capital currently at risk
    swept: float = 0.0              # cumulative removed-and-safe
    tax_provision: float = 0.0      # accrued provision on realised profit
    stake_floor: float = 0.0        # halt if pool falls below this
    sweep_fraction: float = 0.80    # 80% swept out
    tax_rate: float = 0.45          # provision rate on realised profit
    halted: bool = False
    entries: list[dict] = field(default_factory=list)

    def apply_realised(self, pnl: float) -> dict:
        """Apply one closed, realised P&L amount. Returns the ledger entry."""
        entry: dict = {"realised_pnl": pnl, "swept": 0.0, "pool_return": 0.0,
                       "tax_provision_added": 0.0}
        if pnl > 0:
            swept = pnl * self.sweep_fraction
            pool_return = pnl - swept
            provision = pnl * self.tax_rate
            self.swept += swept
            self.pool += pool_return
            self.tax_provision += provision
            entry.update(swept=swept, pool_return=pool_return, tax_provision_added=provision)
        else:
            self.pool += pnl   # losses hit the pool directly (pnl <= 0)
        if self.pool < self.stake_floor:
            self.halted = True
        entry["pool_after"] = self.pool
        entry["swept_after"] = self.swept
        entry["halted"] = self.halted
        self.entries.append(entry)
        return entry
