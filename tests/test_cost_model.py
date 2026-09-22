"""The cost fallback for instruments with no measured telemetry.

Regression tests for a defect found on 2026-09-16. `measured_cost` defaulted to "1.0 pips"
for anything that was not gold or a JPY cross, and priced it with the FX pip convention of
0.0001. On BTCUSD at ~$30,000 that is 1.0 * 0.0001 / 30000, roughly two parts per BILLION:
a spread of effectively zero on the widest-spread instrument in the universe.

Seventeen of twenty-four instruments were costed that way. Every one of them therefore
looked affordable under the new cost ceiling no matter how fast it traded, and the first
D1 sweep reported "24 of 24 affordable" partly on the strength of it.

The general lesson, which is what these tests are really protecting: **a pip is an FX
convention and it does not transfer.** Anything costed across asset classes must be
expressed in a unit that survives the crossing, which is basis points of price.
"""
from __future__ import annotations

import pytest

from backtest.run import _DEFAULT_SPREAD_BPS, measured_cost
from config.instruments import RESEARCH_UNIVERSE, asset_class_of

# Rough live prices, only used to check the cost is dimensionally sane at realistic levels.
REF = {"EURUSD": 1.10, "USDJPY": 150.0, "XAUUSD": 2000.0, "XAGUSD": 25.0,
       "US500": 4500.0, "DE40": 18000.0, "HK50": 17000.0, "AUS200": 7500.0,
       "XTIUSD": 75.0, "XBRUSD": 80.0, "BTCUSD": 30000.0, "ETHUSD": 2000.0,
       "ADAUSD": 0.5, "EURGBP": 0.85, "GBPJPY": 190.0}


@pytest.fixture(autouse=True)
def _no_telemetry(monkeypatch, tmp_path):
    """These tests are about the FALLBACK. Point telemetry at an empty file so they do not
    change meaning when local ticks exist: from 2026-09-16 BTCUSD was measured locally, and
    the scale-invariance test started failing on a measured spread it was never about."""
    from config import settings
    monkeypatch.setattr(settings, "TELEMETRY_DB", str(tmp_path / "no_telemetry.db"))
    monkeypatch.setattr(settings, "SPREAD_SUMMARY", str(tmp_path / "no_summary.json"))


def _bps(symbol: str, ref: float) -> float:
    return measured_cost(symbol, ref_price=ref).cost_per_unit_turnover() * 1e4


def test_no_instrument_is_costed_at_effectively_zero():
    """The exact defect: BTCUSD came out at ~2 parts per billion of round-trip cost."""
    for symbol, ref in REF.items():
        assert _bps(symbol, ref) > 0.1, f"{symbol} is costed at {_bps(symbol, ref):.6f} bps"


def test_every_instrument_in_the_universe_is_costed_sanely():
    """No asset class may fall through to a nonsense number, however it is priced."""
    for symbol in (s for syms in RESEARCH_UNIVERSE.values() for s in syms):
        ref = REF.get(symbol, 100.0)
        assert 0.1 < _bps(symbol, ref) < 100.0, symbol


def test_bitcoin_costs_more_than_the_deepest_fx_pair():
    """The ordering that the pip bug inverted: BTC looked CHEAPER than EURUSD."""
    assert _bps("BTCUSD", 30000.0) > _bps("EURUSD", 1.10)


def test_cost_is_scale_invariant_in_price():
    """A basis point is a fraction of price, so doubling the price must not halve the cost.

    Under the pip convention it did exactly that, which is why an expensive instrument
    quoted in big numbers looked free.
    """
    cheap = _bps("BTCUSD", 30000.0)
    dear = _bps("BTCUSD", 60000.0)
    assert dear == pytest.approx(cheap, rel=0.02)


def test_the_defaults_cover_every_asset_class():
    classes = set(RESEARCH_UNIVERSE)
    assert classes <= set(_DEFAULT_SPREAD_BPS), classes - set(_DEFAULT_SPREAD_BPS)


def test_crypto_is_assumed_wider_than_fx():
    assert _DEFAULT_SPREAD_BPS["crypto"] > _DEFAULT_SPREAD_BPS["fx_major"]


def test_asset_class_lookup_covers_the_reference_prices():
    """A symbol with no class silently gets the catch-all default; catch that here."""
    for symbol in REF:
        assert asset_class_of(symbol) is not None, symbol
