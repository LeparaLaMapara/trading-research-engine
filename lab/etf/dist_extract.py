"""Agenda item 1e: extract issuer distributions and stated returns from archived Satrix PDFs.

Input: PDFs fetched by lab/etf/mdd_fetch.py ($ARTIFACT_ROOT/research-loop/etf-dist-2026-11-22/pdf,
sha256 in index.jsonl). Output: docs/results/etf-distributions-2026-11-22.json (numbers, source
URLs and hashes only; the PDFs stay outside the public repo).

What is read from each document (all regex, no judgement):
  * distributions: (fund, period end, cents per security) from four layouts:
      - finalisation announcement: "quarter ended 30 September 2012" + "aggregate amount of 33.08 cents"
      - quarterly fact statement table: "September 2013   7.82 cps"
      - 2016-2020 fact sheet: "Last four distributions  Jun 2017 21.82 cps"
      - 2024+ MDD block "INCOME DISTRIBUTIONS": "30 Sep 2026   142.37"
  * ex-dates: salient-dates announcements, "quarter ended ..." + 'trade "ex" ... <date>'
  * stated returns: "N year return X%" (fact statements) or "N Year Return X" (2016-2020 MDD),
    with the document's "as at" date. Only documents dated before HOLDOUT_START are used for the
    acceptance test, so the vault stays sealed.
Then: cross-check each issuer distribution against Yahoo's raw and de-duplicated lists (same
quarter window, amount within 1%), rebuild total return with issuer amounts where they exist,
and compare against every pre-holdout stated return. 0 trials (data quality only).

Run: PYTHONPATH=. ARTIFACT_ROOT=/mnt/t/making-money nice python lab/etf/dist_extract.py
"""
import json
import os
import re
import subprocess
from datetime import date

import numpy as np
import pandas as pd

from lab.etf.data_check import clean_close, dedup_dividends, rebuild_tr, yahoo
from scripts.train_zoo import HOLDOUT_START

ROOT = os.path.join(os.environ.get("ARTIFACT_ROOT", "/mnt/t/making-money"),
                    "research-loop", "etf-dist-2026-11-22")
OUT = "docs/results/etf-distributions-2026-11-22.json"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"])}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
MON3["sept"] = 9
TICKER = {"STX40": "STX40.JO", "STXPRO": "STXPRO.JO", "STXGOV": "STXGOV.JO"}


def month_end(y, m):
    return (pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)).normalize()


def _mon(s):
    s = s.lower().rstrip(".")
    return MONTHS.get(s) or MON3.get(s[:4] if s.startswith("sept") else s[:3])


def text_of(path):
    r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True,
                       timeout=120)
    return r.stdout


def identify(t):
    """Fund code from the document text, or None. Order matters: SWIX Top 40 and Satrix
    Property/Bond index unit trusts are NOT the ETFs we need."""
    head = re.sub(r"\s+", " ", t[:1500])
    if re.search(r"Annual Financial Statements|Integrated Annual Report|Supplemental Deed", head, re.I):
        return None  # accounts and deeds: not distribution or performance records
    code = re.search(r"(?:JSE|Instrument) Code\s+(STX[A-Z0-9]+)", t)
    if code:
        return code.group(1)
    if re.search(r"SWIX|INDI|FINI|RESI|DIVI|RAFI", head, re.I):
        return None
    if re.search(r"Satrix 40|STX40|SATRIX 40", head):
        return "STX40"
    return None


def as_at(t):
    """Date the stated returns refer to. Holdings and distributions often carry an older
    'as at' date than the performance table, so look in this order: 'Performance ... as at D M Y',
    'factually correct as at D M Y', the document month in the header (month end), then the
    first 'as at'."""
    def ts(d, mo, y):
        return pd.Timestamp(int(y), _mon(mo), int(d)) if _mon(mo) else None
    flat = re.sub(r"\s+", " ", t)
    for pat in (r"Performance[^.]{0,60}?as at (\d{1,2}) ([A-Z][a-z]+) (\d{4})",
                r"factually correct as at (\d{1,2}) ([A-Z][a-z]+) (\d{4})"):
        m = re.search(pat, flat)
        if m and ts(*m.groups()):
            return ts(*m.groups())
    lines = [x.strip() for x in t.splitlines() if x.strip()][:6]
    for x in lines:
        m = re.fullmatch(r"([A-Z][a-z]+) (\d{4})", x)
        if m and _mon(m.group(1)):
            return month_end(int(m.group(2)), _mon(m.group(1)))
        m = re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]+) (\d{4})", x)
        if m and ts(*m.groups()):
            return ts(*m.groups())
    m = re.search(r"as at (\d{1,2}) ([A-Z][a-z]+) (\d{4})", flat)
    return ts(*m.groups()) if m else None


def distributions(t):
    out = []
    flat = re.sub(r"\s+", " ", t)
    # finalisation announcement
    q = re.search(r"QUARTER ENDED (\d{1,2}) ([A-Za-z]+) (\d{4})", flat, re.I)
    a = re.search(r"aggregate amount of ([\d.]+) cents", flat, re.I)
    if q and a and _mon(q.group(2)):
        out.append((month_end(int(q.group(3)), _mon(q.group(2))), float(a.group(1)),
                    "finalisation"))
    # fact statement table "September 2013   7.82 cps" and fact sheet "Jun 2017 21.82 cps"
    for mo, y, v in re.findall(r"\b([A-Z][a-z]{2,8})\.? (\d{4}) ([\d.]+) ?cps", flat) + \
            re.findall(r"\b([A-Z][a-z]{2}) (\d{4}): ?([\d.]+)", flat):  # 2025 "Dec 2024: 42.53"
        if _mon(mo):
            out.append((month_end(int(y), _mon(mo)), float(v), "table"))
    # 2024+ MDD block
    k = t.find("INCOME DISTRIBUTIONS")
    blk = re.match(r"(.*?)(?:According to|\Z)", t[k + 20:k + 2500], re.S) if k >= 0 else None
    if blk:
        for d, mo, y, v in re.findall(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})\s+([\d.]+)",
                                      blk.group(1)):
            if _mon(mo):
                out.append((month_end(int(y), _mon(mo)), float(v), "mdd"))
        # 2025+ layout: "Mar-26      96.62"
        for mo, yy, v in re.findall(r"\b([A-Z][a-z]{2})-(\d{2})[ \t]+([\d.]+)\b", blk.group(1)):
            if _mon(mo):
                out.append((month_end(2000 + int(yy), _mon(mo)), float(v), "mdd"))
    return out


def ex_dates(t):
    flat = re.sub(r"\s+", " ", t)
    if "SALIENT" not in flat.upper():
        return []
    q = re.search(r"QUARTER ENDED (\d{1,2}) ([A-Za-z]+) (\d{4})", flat, re.I)
    e = re.search(r"trade .{0,3}ex.{0,3} (?:distribution:? )?[A-Za-z]+,? (\d{1,2}) ([A-Za-z]+) "
                  r"(\d{4})", flat, re.I)
    if q and e and _mon(q.group(2)) and _mon(e.group(2)):
        return [(month_end(int(q.group(3)), _mon(q.group(2))),
                 pd.Timestamp(int(e.group(3)), _mon(e.group(2)), int(e.group(1))))]
    return []


def stated_returns(t):
    """[(years, fund_return_pct)] from fact statements ('3 year return 17.98% 18.58%': the first
    number is the fund, the second the index) or 2016-2020 MDDs ('3 Year Return 5.60')."""
    out = []
    for n, v in re.findall(r"\b(\d{1,2}) [Yy]ear [Rr]eturn\s+(-?[\d.]+)%?", t):
        out.append((int(n), float(v)))
    return out


def scan():
    idx = {}
    for line in open(os.path.join(ROOT, "index.jsonl")):
        r = json.loads(line)
        if r.get("file"):
            idx[r["file"]] = r
    docs = []
    for f, r in sorted(idx.items()):
        t = text_of(os.path.join(ROOT, "pdf", f))
        fund = identify(t)
        if fund is None:
            continue
        docs.append({"file": f, "fund": fund, "wayback": r["wayback"], "sha256": r["sha256"],
                     "as_at": as_at(t), "dist": distributions(t), "ex": ex_dates(t),
                     "ret": stated_returns(t)})
    return docs


def merge(docs, fund):
    """Issuer distribution per period end; conflicting amounts are kept and flagged."""
    by = {}
    for d in docs:
        if d["fund"] != fund:
            continue
        for p, v, kind in d["dist"]:
            by.setdefault(p, set()).add(round(v, 2))
    exd = {}
    for d in docs:
        if d["fund"] == fund:
            for p, e in d["ex"]:
                exd[p] = e
    rows = []
    for p in sorted(by):
        vals = sorted(by[p])
        rows.append({"period_end": str(p.date()), "cps": vals[0] if len(vals) == 1 else None,
                     "conflict": vals if len(vals) > 1 else None,
                     "ex_date": str(exd[p].date()) if p in exd else None})
    return rows


def crosscheck(rows, raw, ded):
    """For each issuer distribution, the Yahoo entries in (period_end - 35d, period_end + 60d)."""
    res = []
    for r in rows:
        if r["cps"] is None:
            continue
        p = pd.Timestamp(r["period_end"])
        win = lambda s: s[(s.index > p - pd.Timedelta(days=35)) & (s.index < p + pd.Timedelta(days=60))]
        wr, wd = win(raw), win(ded)
        match = [str(i.date()) for i, a in wd.items() if abs(a - r["cps"]) <= 0.01 * r["cps"] + 0.01]
        res.append({**r, "yahoo_raw": [[str(i.date()), a] for i, a in wr.items()],
                    "yahoo_dedup_match": match,
                    "status": "match" if match else ("missing" if wd.empty else "different")})
    return res


def issuer_divs(rows, ded):
    """Dividend series for the rebuild: issuer amount, dated at the issuer ex-date if known,
    else the matched Yahoo date, else 5 days before period end (same month; UNVERIFIED date).
    Yahoo amounts are kept for periods the issuer documents do not cover."""
    s, covered = {}, []
    for r in rows:
        if r["cps"] is None or r["cps"] == 0:
            if r["cps"] == 0:
                covered.append(pd.Timestamp(r["period_end"]))
            continue
        p = pd.Timestamp(r["period_end"])
        if r.get("ex_date"):
            dt = pd.Timestamp(r["ex_date"])
        elif r.get("yahoo_dedup_match"):
            dt = pd.Timestamp(r["yahoo_dedup_match"][0])
        else:
            dt = p - pd.Timedelta(days=5)
        s[dt] = s.get(dt, 0) + r["cps"]
        covered.append(p)
    for i, a in ded.items():  # Yahoo entries in quarters the issuer list does not cover
        if not any(p - pd.Timedelta(days=35) < i < p + pd.Timedelta(days=60) for p in covered):
            s[i] = s.get(i, 0) + a
    return pd.Series(s, dtype=float).sort_index()


def exdate_test(close, divs, before=HOLDOUT_START):
    """Which date of a Yahoo duplicate pair carries the price drop? For each pair (same amount,
    <= 45 days apart) take the close-to-close return on each date in units of the dividend
    yield (about -1 on the true ex-date, about 0 otherwise). Split by whether the pair crosses a
    month end (the only case that changes monthly returns); t of the paired difference.
    Only pairs whose later date is before `before` (the holdout start) are used. A run of three
    equal amounts counts as two overlapping pairs."""
    divs = divs[divs.index < before]
    r = close / close.shift(1) - 1
    it, rows = list(divs.items()), []
    for i in range(len(it) - 1):
        (a, x), (b, y) = it[i], it[i + 1]
        if abs(x - y) < 1e-6 and (b - a).days <= 45:
            k1, k2 = close.index.searchsorted(a), close.index.searchsorted(b)
            if k1 < 1 or k2 >= len(close):
                continue
            rows.append((a.to_period("M") != b.to_period("M"),
                         r.iloc[k1] / (x / close.iloc[k1 - 1]), r.iloc[k2] / (x / close.iloc[k2 - 1])))
    out = {}
    for cross in (False, True):
        v = np.array([(p, q) for m, p, q in rows if m == cross])
        if len(v) < 2:
            continue
        d = v[:, 1] - v[:, 0]
        out["cross_month" if cross else "same_month"] = {
            "pairs": int(len(v)), "first_date_ret_over_yield": round(float(v[:, 0].mean()), 2),
            "second_date_ret_over_yield": round(float(v[:, 1].mean()), 2),
            "t_second_minus_first": round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 1)}
    return out


def ann(tr, end, years):
    tr = tr[tr.index <= end]
    if tr.empty:
        return None
    start = end - pd.DateOffset(years=years)
    if tr.index[0] > start + pd.Timedelta(days=10):
        return None
    a, b = tr[tr.index <= start].iloc[-1] if (tr.index <= start).any() else tr.iloc[0], tr.iloc[-1]
    return 100 * ((b / a) ** (1 / years) - 1)


def main():
    docs = scan()
    out = {"generated": str(date.today()), "holdout_start": str(HOLDOUT_START.date()),
           "documents": [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                          for k, v in d.items() if k in ("file", "fund", "wayback", "sha256", "as_at")}
                         | {"n_dist": len(d["dist"]), "n_ex": len(d["ex"]), "n_ret": len(d["ret"])}
                         for d in docs], "funds": {}}
    for fund, tk in TICKER.items():
        rows = merge(docs, fund)
        if not rows:
            continue
        df, divs, _s, _m, sha = yahoo(tk)
        ded = dedup_dividends(divs)
        close, _bad = clean_close(df["close"])
        cc = crosscheck(rows, divs, ded)
        tr_y = rebuild_tr(close, ded)
        tr_i = rebuild_tr(close, issuer_divs(cc, ded))
        tests = []
        for d in docs:
            if d["fund"] != fund or d["as_at"] is None or d["as_at"] >= HOLDOUT_START:
                continue
            for n, v in d["ret"]:
                ry, ri = ann(tr_y, d["as_at"], n), ann(tr_i, d["as_at"], n)
                if ri is None:
                    continue
                tests.append({"as_at": str(d["as_at"].date()), "years": n, "stated": v,
                              "rebuilt_yahoo": round(ry, 2), "rebuilt_issuer": round(ri, 2),
                              "gap_yahoo": round(ry - v, 2), "gap_issuer": round(ri - v, 2),
                              "source": d["wayback"]})
        tests = list({(t["as_at"], t["years"]): t for t in tests}.values())
        gi = np.array([t["gap_issuer"] for t in tests]) if tests else np.array([])
        gy = np.array([t["gap_yahoo"] for t in tests]) if tests else np.array([])
        years = {}
        for r in cc:
            y = r["period_end"][:4]
            years.setdefault(y, {"issuer": 0, "match": 0, "missing": 0, "different": 0})
            years[y]["issuer"] += 1
            years[y][r["status"]] += 1
        out["funds"][fund] = {
            "yahoo_sha256": sha, "exdate_test": exdate_test(close, divs), "issuer_periods": len(rows),
            "first_period": rows[0]["period_end"], "last_period": rows[-1]["period_end"],
            "conflicts": [r for r in rows if r["conflict"]],
            "by_year": years, "crosscheck": cc, "return_tests": sorted(tests, key=lambda t: (t["as_at"], t["years"])),
            "median_abs_gap_issuer": float(np.median(np.abs(gi))) if gi.size else None,
            "median_abs_gap_yahoo": float(np.median(np.abs(gy))) if gy.size else None,
            "max_abs_gap_issuer": float(np.max(np.abs(gi))) if gi.size else None,
        }
    df, divs, _s, _m, sha = yahoo("ETFBND.JO")
    out["exdate_test_ETFBND"] = exdate_test(clean_close(df["close"])[0], divs)
    # covered windows: the stated-return window starts on or after the first issuer period
    for fund, v in out["funds"].items():
        first = pd.Timestamp(v["first_period"]) - pd.offsets.QuarterEnd(1)
        cov = [t for t in v["return_tests"]
               if pd.Timestamp(t["as_at"]) - pd.DateOffset(years=t["years"]) >= first]
        g = np.array([t["gap_issuer"] for t in cov])
        gy = np.array([t["gap_yahoo"] for t in cov])
        c13 = [t for t in cov if pd.Timestamp(t["as_at"]) - pd.DateOffset(years=t["years"])
               >= pd.Timestamp("2013-01-01")]
        g13 = np.array([t["gap_yahoo"] for t in c13])
        med = lambda a: round(float(np.median(np.abs(a))), 3) if a.size else None
        mx = lambda a: round(float(np.max(np.abs(a))), 3) if a.size else None
        v["covered_windows"] = {"n": len(cov), "median_abs_gap": med(g), "max_abs_gap": mx(g),
                                "yahoo_only_median_abs_gap": med(gy),
                                "yahoo_only_max_abs_gap": mx(gy),
                                "from_2013_n": len(c13), "from_2013_yahoo_only_median": med(g13),
                                "from_2013_yahoo_only_max": mx(g13)}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    for fund, v in out["funds"].items():
        print(fund, v["issuer_periods"], v["first_period"], v["last_period"],
              "tests", len(v["return_tests"]), "gap issuer", v["median_abs_gap_issuer"],
              "yahoo", v["median_abs_gap_yahoo"], "max", v["max_abs_gap_issuer"],
              "covered", v["covered_windows"], "exdate", v["exdate_test"])
        for y, c in sorted(v["by_year"].items()):
            print("  ", y, c)


if __name__ == "__main__":
    main()
