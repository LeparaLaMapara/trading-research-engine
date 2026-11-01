"""E17 sources: official central bank and statistics feeds (fixed in the pre-registration).

Free, no login. Parsed with the standard library: RSS 2.0, RSS 1.0 (RDF) and Atom all reduce
to items of (source, title, link, published, summary).
"""
from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import pandas as pd

FEEDS = {
    "fed":     ("https://www.federalreserve.gov/feeds/press_all.xml", "USD"),
    "bls_emp": ("https://www.bls.gov/feed/empsit.rss", "USD"),
    "bls_cpi": ("https://www.bls.gov/feed/cpi.rss", "USD"),
    "bea":     ("https://apps.bea.gov/rss/rss.xml", "USD"),
    "ecb":     ("https://www.ecb.europa.eu/rss/press.html", "EUR"),
    "boe":     ("https://www.bankofengland.co.uk/rss/news", "GBP"),
    "boj":     ("https://www.boj.or.jp/en/rss/whatsnew.xml", "JPY"),
    "snb":     ("https://www.snb.ch/public/en/rss/pressrel", "CHF"),
    "boc":     ("https://www.bankofcanada.ca/content_type/press-releases/feed/", "CAD"),
    "rba":     ("https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "AUD"),
    "rbnz":    ("https://www.rbnz.govt.nz/feeds/news", "NZD"),
}
HEADERS = {"User-Agent": "Mozilla/5.0 trading-research-engine/0.1 (research reader)"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, *names: str) -> str:
    for c in el:
        if _local(c.tag) in names:
            if _local(c.tag) == "link" and c.get("href"):
                return c.get("href")
            if (c.text or "").strip():
                return c.text.strip()
    return ""


def _when(text: str) -> float | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        t = pd.Timestamp(text)
        return (t if t.tzinfo else t.tz_localize("UTC")).timestamp()
    except (ValueError, TypeError):
        return None


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def item_id(source: str, link: str, title: str) -> str:
    return hashlib.sha256(f"{source}|{link}|{title}".encode()).hexdigest()[:16]


def parse(source: str, content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = strip_html(_child(el, "title"))
        link = _child(el, "link", "id")
        if not title:
            continue
        out.append({"id": item_id(source, link, title), "source": source, "title": title, "link": link,
                    "published_utc": _when(_child(el, "pubDate", "published", "updated", "date")),
                    "summary": strip_html(_child(el, "description", "summary", "content"))[:1500]})
    return out


def fetch(source: str, timeout: int = 30) -> list[dict]:
    import requests
    r = requests.get(FEEDS[source][0], headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return parse(source, r.content)


def page_text(url: str, limit: int = 4000, timeout: int = 30) -> str:
    """The readable text of an item's page, capped; '' when it cannot be read (PDFs included)."""
    import requests
    if not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        body = re.search(r"(?is)<(main|article)\b.*?</\1>", r.text)   # skip menus when marked up
        return strip_html(body.group(0) if body else r.text)[:limit]
    except requests.RequestException:
        return ""
