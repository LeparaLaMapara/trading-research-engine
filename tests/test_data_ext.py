"""Outside data fetchers: parsing and bookkeeping, with the network replaced by fixtures."""
import datetime as dt
import io
import zipfile

import pandas as pd

from data_ext import fetch as F


class _Resp:
    def __init__(self, status, text="", content=b"", js=None):
        self.status_code, self.text, self.content, self._js = status, text, content, js

    def json(self):
        return self._js


def test_months_inclusive():
    got = list(F._months(dt.date(2019, 11, 1), dt.date(2020, 2, 10)))
    assert got == [(2019, 11), (2019, 12), (2020, 1), (2020, 2)]


def test_every_cot_name_maps_to_one_instrument():
    names = [n for ns in F.COT_MARKETS.values() for n in ns]
    assert len(names) == len(set(names))


def test_rates_parse_and_failed_series_are_listed_not_filled(monkeypatch):
    def fake_get(url, **kw):
        if url.endswith("id=DFF"):
            return _Resp(200, "observation_date,DFF\n2026-09-01,4.33\n2026-09-02,.\n")
        return _Resp(404, "<html>")
    monkeypatch.setattr(F, "get", fake_get)
    df, failed = F.fetch_rates()
    assert list(df["series"]) == ["DFF"] and df["value"].iloc[0] == 4.33
    assert len(df) == 1                                   # "." is a gap, dropped not guessed
    assert len(failed) == len(F.FRED) - 1


def test_cot_instruments_join_renamed_markets(monkeypatch):
    rows = [{"market_and_exchange_names": "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
             "report_date_as_yyyy_mm_dd": "2021-01-05T00:00:00.000", "open_interest_all": "100",
             "noncomm_positions_long_all": "60", "noncomm_positions_short_all": "20"},
            {"market_and_exchange_names": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE ",
             "report_date_as_yyyy_mm_dd": "2023-01-03T00:00:00.000", "open_interest_all": "200",
             "noncomm_positions_long_all": "50", "noncomm_positions_short_all": "90"}]
    monkeypatch.setattr(F, "get", lambda url, **kw: _Resp(200, js=rows))
    df, failed = F.fetch_cot()
    assert list(df["instrument"]) == ["GBP", "GBP"]
    assert list(df["noncomm_net"]) == [40, -40]
    assert df["noncomm_net_share_of_oi"].iloc[1] == -0.2
    assert "CFTC: no rows for GBP" not in failed and "CFTC: no rows for EUR" in failed


def test_binance_funding_zip_parsed(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ETHUSDT-fundingRate-2024-01.csv",
                   "calc_time,funding_interval_hours,last_funding_rate\n"
                   "1704067200000,8,0.0001\n1704096000000,8,-0.00005\n")
    monkeypatch.setattr(F, "FUNDING_SYMBOLS", ["ETHUSDT"])

    def fake_get(url, **kw):
        if "binance" in url and "2024-01" in url:
            return _Resp(200, content=buf.getvalue())
        if "binance" in url:
            return _Resp(404)
        return _Resp(503, js={})
    monkeypatch.setattr(F, "get", fake_get)
    df, failed = F.fetch_funding()
    b = df[df["venue"] == "binance"]
    assert list(b["rate"]) == [0.0001, -0.00005]
    assert b["ts"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert any("OKX" in f for f in failed) and any("BitMEX" in f for f in failed)
