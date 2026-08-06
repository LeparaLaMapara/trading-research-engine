"""The Risk Officer must fail closed until configured (spec §1/§3.6)."""
from risk.limits import Limits, RiskOfficer


def test_denies_when_unconfigured():
    d = RiskOfficer().permit()
    assert d.allowed is False
    assert "not configured" in d.reason


def test_denies_even_when_limits_set_until_checks_built():
    # Phase 1d not implemented yet: still deny even with numbers present.
    limits = Limits(2.0, 10.0, 1.0, 20.0, 10.0, 30.0)
    d = RiskOfficer(limits).permit()
    assert d.allowed is False
