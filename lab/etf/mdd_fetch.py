"""Agenda item 1e: fetch issuer fact sheets (MDDs) and announcements.

Issuer sites are not crawled (Sygnia sits behind a bot wall, 1nvest returns 403; recorded as
blocked). Sources, all fetched 2 s apart, each file's sha256 written to index.jsonl:
  1. Wayback copies of Satrix PDFs under satrix.co.za/media/<id> (2017-2026 fact sheets).
     CDX list: http://web.archive.org/cdx/search/cdx?url=satrix.co.za/media/*
       &filter=mimetype:application/pdf&filter=statuscode:200&collapse=digest
       &fl=timestamp,original,digest,length                 -> cdx_satrix_media.txt
     Every file whose first lines carry "Minimum Disclosure" or a wanted fund name is kept.
  2. Older Satrix 40 documents (fact statements, distribution announcements, 2006-2016).
     CDX list: same query with url=satrix.co.za&matchType=domain -> cdx_satrix_all.txt, rows with
     timestamp >= 20080101 -> cdx_satrix_old.txt; run with a URL regex, all matches kept:
       python lab/etf/mdd_fetch.py $ROOT/cdx_satrix_old.txt 'satrix ?40|stx40|top ?40'
     (awk compared the timestamps numerically, so 2006-2007 snapshots came through too.)
  3. --live: the current fact sheet from satrix.co.za/fund/mdd/<code> for STX40, STXPRO, STXGOV
     (3 requests; the page itself is public, product pages returned 500).
PDFs never enter the repo (public).

Run: PYTHONPATH=. ARTIFACT_ROOT=/mnt/t/making-money nice python lab/etf/mdd_fetch.py [args]
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.join(os.environ.get("ARTIFACT_ROOT", "/mnt/t/making-money"),
                    "research-loop", "etf-dist-2026-11-22")
CDX = os.path.join(ROOT, "cdx_satrix_media.txt")
PDF_DIR = os.path.join(ROOT, "pdf")
INDEX = os.path.join(ROOT, "index.jsonl")
# Fund names as they appear on the first line of a Satrix MDD.
WANT = {"Satrix 40 ETF": "STX40", "Satrix Property ETF": "STXPRO",
        "Satrix SA Bond ETF": "STXGOV", "Satrix GOVI ETF": "STXGOV",
        "Satrix Local Bond ETF": "STXGOV",
        "Satrix MSCI World Feeder ETF": "STXWDM", "Satrix MSCI World ETF": "STXWDM",
        "Satrix S&P 500 Feeder ETF": "STX500", "Satrix S&P 500 ETF": "STX500"}


def first_lines(path, n=6):
    try:
        out = subprocess.run(["pdftotext", "-l", "1", path, "-"], capture_output=True,
                             text=True, timeout=60).stdout
    except Exception:
        return []
    return [x.strip() for x in out.splitlines() if x.strip()][:n]


def live():
    os.makedirs(PDF_DIR, exist_ok=True)
    for code in ("STX40", "STXPRO", "STXGOV"):
        url = f"https://satrix.co.za/fund/mdd/{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "research-script/1.0"})
        data = urllib.request.urlopen(req, timeout=90).read()
        sha = hashlib.sha256(data).hexdigest()
        name = f"{code}_LIVE{time.strftime('%Y%m%d')}_{sha[:12]}.pdf"
        open(os.path.join(PDF_DIR, name), "wb").write(data)
        rec = {"wayback": url, "timestamp": "LIVE" + time.strftime("%Y%m%d"), "original": url,
               "sha256": sha, "head": first_lines(os.path.join(PDF_DIR, name)), "fund": code,
               "file": name}
        with open(INDEX, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(code, name, flush=True)
        time.sleep(2)


def main():
    """argv: [cdx_file] [url_regex]. With a regex, only CDX rows whose decoded URL matches are
    fetched and every fetched PDF is kept (older Satrix document paths, 2009-2016)."""
    import re
    import urllib.parse
    cdx = sys.argv[1] if len(sys.argv) > 1 else CDX
    pat = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
    os.makedirs(PDF_DIR, exist_ok=True)
    done = set()
    if os.path.exists(INDEX):
        done = {json.loads(x)["wayback"] for x in open(INDEX)}
    rows = [x.split() for x in open(cdx) if x.strip()]
    if pat:
        rows = [r for r in rows if "/media/" not in r[1]
                and pat.search(urllib.parse.unquote(r[1]))]
    for ts, orig, digest, _len in rows:
        url = f"http://web.archive.org/web/{ts}id_/{orig}"
        if url in done:
            continue
        tmp = os.path.join(PDF_DIR, "_tmp.pdf")
        rec = {"wayback": url, "timestamp": ts, "original": orig, "cdx_digest": digest}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-script/1.0"})
            data = urllib.request.urlopen(req, timeout=90).read()
            open(tmp, "wb").write(data)
            rec["sha256"] = hashlib.sha256(data).hexdigest()
            head = first_lines(tmp)
            rec["head"] = head
            fund = next((WANT[h] for h in head if h in WANT), None)
            rec["fund"] = fund
            is_mdd = any("Minimum Disclosure" in h for h in head)
            if fund or is_mdd or pat:  # keep every MDD; funds are re-identified in mdd_extract
                keep = os.path.join(PDF_DIR, f"{fund or ('DOC' if pat else 'MDD')}_{ts}_{rec['sha256'][:12]}.pdf")
                os.replace(tmp, keep)
                rec["file"] = os.path.basename(keep)
            else:
                os.remove(tmp)
        except Exception as e:  # recorded, retried on a later run
            rec["error"] = repr(e)[:200]
        if "error" not in rec:
            with open(INDEX, "a") as f:
                f.write(json.dumps(rec) + "\n")
        print(ts, rec.get("fund"), (rec.get("head") or [""])[:1], rec.get("error", ""),
              flush=True)
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(live() if sys.argv[1:2] == ["--live"] else main())
