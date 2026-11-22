"""Parser checks for lab/etf/dist_extract.py on text shaped like the real Satrix documents."""
import pandas as pd

from lab.etf.dist_extract import (as_at, crosscheck, distributions, ex_dates, identify,
                                  issuer_divs, stated_returns)

FINAL = """STX40 - SATRIX 40 PORTFOLIO
DISTRIBUTION FINALISATION ANNOUNCEMENT – QUARTER ENDED 30 SEPTEMBER 2012
An aggregate amount of     33.08   cents   (R0.3308)   per   Satrix     40   security
"""
SALIENT = """STX40 - SATRIX 40 PORTFOLIO - Distribution Announcement - Salient
DISTRIBUTION ANNOUNCEMENT – SALIENT DATES – QUARTER ENDED 30 JUNE
2012
Last day to trade “cum”                         Friday, 22 June 2012
distribution:
Securities trade “ex”                           Monday, 25 June 2012
"""
MDD2019 = """Satrix 40 ETF
                                                       February 2019
   Instrument Code                                       STX40
   Last four distributions                               Dec 2018 16.60 cps Sep 2018 39.10 cps
   Daily price information                               www.satrix.co.za      as at 31 December 2018
                 Performance (Annualised) as at 28 February 2019 on a rolling monthly basis
                                         1 Year Return                -0.33           -0.34
                                         3 Year Return                 7.02            7.27
"""
MDD2026 = """Satrix 40 ETF
Minimum Disclosure Document
31 October 2026
   JSE Code                                 STX40
  INCOME DISTRIBUTIONS
                                    CPS (Cents Per Share)
   30 Sep 2026                                                 142.37   RISK PROFILE
   30 Jun 2026                                                  98.31
  According to the Fund's Supplemental Deed
"""
SWIX = """Satrix SWIX Top 40
September 2013                                 7.82 cps
"""


def test_identify():
    assert identify(FINAL) == "STX40"
    assert identify(MDD2019) == "STX40"
    assert identify(SWIX) is None


def test_distribution_layouts():
    assert distributions(FINAL) == [(pd.Timestamp("2012-09-30"), 33.08, "finalisation")]
    d = {(p, v) for p, v, _ in distributions(MDD2019)}
    assert d == {(pd.Timestamp("2018-12-31"), 16.60), (pd.Timestamp("2018-09-30"), 39.10)}
    d = {(p, v) for p, v, _ in distributions(MDD2026)}
    assert d == {(pd.Timestamp("2026-09-30"), 142.37), (pd.Timestamp("2026-06-30"), 98.31)}


def test_ex_date_and_return_date():
    assert ex_dates(SALIENT) == [(pd.Timestamp("2012-06-30"), pd.Timestamp("2012-06-25"))]
    # performance date wins over the holdings 'as at' date
    assert as_at(MDD2019) == pd.Timestamp("2019-02-28")
    assert stated_returns(MDD2019) == [(1, -0.33), (3, 7.02)]


def test_crosscheck_and_merge():
    rows = [{"period_end": "2012-09-30", "cps": 33.08, "conflict": None, "ex_date": None},
            {"period_end": "2013-03-31", "cps": 20.0, "conflict": None, "ex_date": "2013-03-22"}]
    raw = pd.Series({pd.Timestamp("2013-03-22"): 20.0, pd.Timestamp("2013-04-20"): 20.0,
                     pd.Timestamp("2013-06-25"): 30.0})
    ded = pd.Series({pd.Timestamp("2013-04-20"): 20.0, pd.Timestamp("2013-06-25"): 30.0})
    cc = crosscheck(rows, raw, ded)
    assert [c["status"] for c in cc] == ["missing", "match"]
    s = issuer_divs(cc, ded)
    # issuer amounts at the issuer ex-date (or 5 days before period end), Yahoo kept only
    # for the quarter the issuer list does not cover
    assert s.to_dict() == {pd.Timestamp("2012-09-25"): 33.08, pd.Timestamp("2013-03-22"): 20.0,
                           pd.Timestamp("2013-06-25"): 30.0}


# copied from the real 2025 Satrix fact sheet layout (STX40, February 2025; pdftotext -layout)
FS2025 = """(Fund Fact Sheet)
Satrix 40 ETF
February 2025
Benchmark                               FTSE/JSE Top 40 (J200)             5 year      15.20
Last four distributions                 Dec 2024: 42.53 cps Sep 2024: 69.79             8.50
                                        Jun 2024: 86.24 cps Mar 2024: 37.31
"""
# real 2026 MDD layout (STX40, 30 April 2026)
MDD2026B = """Satrix 40 ETF
Minimum Disclosure Document
30 April 2026
     INCOME DISTRIBUTIONS                                                        CPS

      Mar-26                                                                     96.62

      Dec-25                                                                     55.71
"""


def test_2025_2026_layouts():
    d = {(str(p.date()), v) for p, v, _ in distributions(FS2025)}
    assert d == {("2024-12-31", 42.53), ("2024-09-30", 69.79), ("2024-06-30", 86.24),
                 ("2024-03-31", 37.31)}
    assert as_at(FS2025) == pd.Timestamp("2025-02-28")
    d = {(str(p.date()), v) for p, v, _ in distributions(MDD2026B)}
    assert d == {("2026-03-31", 96.62), ("2025-12-31", 55.71)}
    assert as_at(MDD2026B) == pd.Timestamp("2026-04-30")
