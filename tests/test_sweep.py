"""The 20/80 ratchet: sweep math, loss handling, and the stake-floor halt."""
from ledger.sweep import SweepState


def test_profit_splits_20_80_and_accrues_tax():
    s = SweepState(pool=100.0, tax_rate=0.45)
    e = s.apply_realised(10.0)
    assert round(e["swept"], 2) == 8.0          # 80% out
    assert round(e["pool_return"], 2) == 2.0     # 20% back
    assert round(s.pool, 2) == 102.0
    assert round(s.swept, 2) == 8.0
    assert round(s.tax_provision, 2) == 4.5      # 45% of realised profit


def test_losses_hit_pool_and_are_not_swept():
    s = SweepState(pool=100.0)
    s.apply_realised(-15.0)
    assert round(s.pool, 2) == 85.0
    assert s.swept == 0.0


def test_stake_floor_halts():
    s = SweepState(pool=100.0, stake_floor=90.0)
    s.apply_realised(-5.0)
    assert not s.halted        # 95 > floor
    s.apply_realised(-10.0)
    assert s.halted            # 85 < floor
