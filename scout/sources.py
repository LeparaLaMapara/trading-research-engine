"""Real research sources for the Scout. No fabrication: everything here FETCHES.

arXiv is the primary source: free, no API key, and every result carries a resolvable
identifier (the arXiv id) plus the real abstract text. The anti-hallucination rule (spec
§5) is enforced upstream by only ever handing the LLM text that was actually fetched here.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import requests

ARXIV_API = "http://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Quant-finance + statistical-ML categories worth hunting across disciplines.
DEFAULT_CATEGORIES = ["q-fin.TR", "q-fin.PM", "q-fin.ST", "q-fin.CP", "stat.ML"]


def _arxiv_id(entry_id: str) -> str:
    """'http://arxiv.org/abs/2401.01234v2' -> '2401.01234v2' (a resolvable identifier)."""
    return entry_id.rsplit("/abs/", 1)[-1] if "/abs/" in entry_id else entry_id


def parse_arxiv_atom(xml_text: str) -> list[dict]:
    """Parse an arXiv Atom feed into paper dicts. Pure; unit-tested on a fixture."""
    root = ET.fromstring(xml_text)
    papers: list[dict] = []
    for e in root.findall("atom:entry", _NS):
        title = (e.findtext("atom:title", default="", namespaces=_NS) or "").strip()
        summary = (e.findtext("atom:summary", default="", namespaces=_NS) or "").strip()
        eid = (e.findtext("atom:id", default="", namespaces=_NS) or "").strip()
        published = (e.findtext("atom:published", default="", namespaces=_NS) or "").strip()
        authors = [a.findtext("atom:name", default="", namespaces=_NS)
                   for a in e.findall("atom:author", _NS)]
        if not eid or not title:
            continue
        papers.append({
            "identifier": f"arXiv:{_arxiv_id(eid)}",
            "url": eid,
            "title": " ".join(title.split()),
            "abstract": " ".join(summary.split()),
            "authors": [a for a in authors if a],
            "published": published,
        })
    return papers


def fetch_arxiv(categories: list[str] | None = None, keywords: str | None = None,
                max_results: int = 5) -> list[dict]:
    """Fetch the most recent papers for the given categories (and optional keywords).

    Returns real papers with resolvable arXiv identifiers and their actual abstracts.
    Never invents entries: on any error it returns an empty list.
    """
    cats = categories or DEFAULT_CATEGORIES
    cat_q = " OR ".join(f"cat:{c}" for c in cats)
    search = f"({cat_q})"
    if keywords:
        search += f" AND (all:{keywords})"
    try:
        resp = requests.get(ARXIV_API, params={
            "search_query": search,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }, timeout=30)
        resp.raise_for_status()
        return parse_arxiv_atom(resp.text)
    except Exception as exc:  # noqa: BLE001
        print(f"arxiv fetch failed: {exc}")
        return []


def fetch_arxiv_search(query: str, max_results: int = 25) -> list[dict]:
    """The most relevant arXiv papers for a phrase, across all categories and years."""
    try:
        resp = requests.get(ARXIV_API, params={
            "search_query": f'all:"{query}"', "start": 0, "max_results": max_results,
            "sortBy": "relevance", "sortOrder": "descending"}, timeout=60)
        resp.raise_for_status()
        return parse_arxiv_atom(resp.text)
    except Exception as exc:  # noqa: BLE001
        print(f"arxiv search failed for {query!r}: {exc}")
        return []


def keyword_clause(keywords: str) -> str:
    """'power law OR criticality' -> '(all:"power law" OR all:criticality)'."""
    terms = [t.strip() for t in keywords.split(" OR ") if t.strip()]
    parts = [f'all:"{t}"' if " " in t else f"all:{t}" for t in terms]
    return "(" + " OR ".join(parts) + ")"


def fetch_arxiv_window(category: str, keywords: str | None, since: str, until: str,
                       max_results: int = 30) -> list[dict]:
    """Papers submitted to one category between two dates (YYYYMMDD), newest first.

    Same guarantees as fetch_arxiv: real ids and real abstracts, or an empty list.
    """
    search = f"cat:{category} AND submittedDate:[{since}0000 TO {until}2359]"
    if keywords:
        search += f" AND {keyword_clause(keywords)}"
    try:
        resp = requests.get(ARXIV_API, params={
            "search_query": search, "start": 0, "max_results": max_results,
            "sortBy": "submittedDate", "sortOrder": "descending",
        }, timeout=60)
        resp.raise_for_status()
        return parse_arxiv_atom(resp.text)
    except Exception as exc:  # noqa: BLE001 - a failed field is reported, not fatal
        print(f"arxiv fetch failed for {category}: {exc}")
        return []


OPENALEX_API = "https://api.openalex.org/works"


def abstract_from_inverted_index(index: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}. Rebuild the text in order."""
    if not index:
        return ""
    slots: dict[int, str] = {}
    for word, positions in index.items():
        for p in positions:
            slots[int(p)] = word
    return " ".join(slots[i] for i in sorted(slots))


def parse_openalex(payload: dict) -> list[dict]:
    """OpenAlex /works JSON -> paper dicts. Works without an abstract are dropped: the reading
    room never reasons about a paper whose text it does not hold."""
    papers: list[dict] = []
    for w in payload.get("results", []):
        abstract = abstract_from_inverted_index(w.get("abstract_inverted_index"))
        title = " ".join((w.get("title") or "").split())
        if not abstract or not title:
            continue
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        wid = (w.get("id") or "").rsplit("/", 1)[-1]
        src = (w.get("primary_location") or {}).get("source") or {}
        venue = src.get("display_name")
        papers.append({
            "identifier": f"doi:{doi}" if doi else f"openalex:{wid}",
            "url": w.get("doi") or w.get("id") or "",
            "title": title,
            "abstract": " ".join(abstract.split()),
            "authors": [a.get("author", {}).get("display_name", "")
                        for a in w.get("authorships", [])][:8],
            "published": w.get("publication_date") or "",
            "venue": venue or "",
            "issn": list(src.get("issn") or []),
            # A free, legal full-text copy when one exists (author versions, NBER, SSRN).
            "oa_pdf": ((w.get("best_oa_location") or {}).get("pdf_url")
                       or (w.get("open_access") or {}).get("oa_url") or ""),
            "cited_by": int(w.get("cited_by_count") or 0),
        })
    return papers


def fetch_openalex(search: str, since: str | None = None, classic: bool = False,
                   per_page: int = 15, issns: list[str] | None = None) -> list[dict]:
    """Works matching a phrase (OpenAlex search takes AND, OR, NOT). `since` (YYYY-MM-DD) for
    new work; `classic` gives the most relevant well-cited work (the foundations of a topic); `issns` keeps only
    those journals. Empty list on any failure, never a made-up entry."""
    filters = ["has_abstract:true"]
    if since:
        filters.append(f"from_publication_date:{since}")
    if issns:
        filters.append("primary_location.source.issn:" + "|".join(issns))
    params = {"search": search, "filter": ",".join(filters), "per-page": per_page}
    if classic:
        # Most relevant among well-cited work. Sorting by citations alone returns famous papers
        # that merely share a word with the query (a funding-rate search found hydrology).
        params["filter"] += ",cited_by_count:>30"
        params["sort"] = "relevance_score:desc"
    else:
        params["sort"] = "publication_date:desc"
    for attempt in range(3):
        try:
            time.sleep(3)                         # stay under OpenAlex's anonymous rate limit
            resp = requests.get(OPENALEX_API, params=params, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            resp.raise_for_status()
            return parse_openalex(resp.json())
        except Exception as exc:  # noqa: BLE001
            print(f"openalex fetch failed for {search!r}: {exc}")
            return []
    return []


class _TextOnly(HTMLParser):
    """Collect visible text, skipping scripts, styles, navigation and the bibliography."""

    SKIP = {"script", "style", "nav", "header", "footer", "math"}

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "math" and not self.depth:
            # arXiv's MathML carries the TeX source in alttext; keep formulas readable.
            alt = dict(attrs).get("alttext")
            if alt:
                self.parts.append(f" ${alt}$ ")
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextOnly()
    p.feed(html)
    return " ".join(" ".join(p.parts).split())


def fetch_arxiv_fulltext(identifier: str, max_chars: int = 120_000) -> tuple[str, str]:
    """Full text of an arXiv paper from its HTML rendering. Returns (text, depth) where depth is
    'full', 'truncated at N chars' or '' when no HTML version exists (older or TeX-failing
    papers). Nothing is ever cut silently: the depth says how much was read."""
    if not identifier.startswith("arXiv:"):
        return "", ""
    aid = identifier.split(":", 1)[1]
    try:
        resp = requests.get(f"https://arxiv.org/html/{aid}", timeout=60)
        if resp.status_code != 200 or "<html" not in resp.text[:2000].lower():
            return "", ""
        text = html_to_text(resp.text)
    except Exception as exc:  # noqa: BLE001
        print(f"arxiv full text failed for {aid}: {exc}")
        return "", ""
    if len(text) < 2000:
        return "", ""
    if len(text) > max_chars:
        return text[:max_chars], f"truncated at {max_chars} chars of {len(text)}"
    return text, "full"


def pdf_to_text(data: bytes, max_chars: int = 120_000) -> tuple[str, str]:
    """Text of a PDF, with the same depth labels as fetch_arxiv_fulltext. '' when the bytes are
    not a PDF (many open-access links land on a web page instead)."""
    if not data.startswith(b"%PDF"):
        return "", ""
    try:
        from pypdf import PdfReader
        import io as _io
        text = " ".join((pg.extract_text() or "") for pg in PdfReader(_io.BytesIO(data)).pages)
    except Exception as exc:  # noqa: BLE001 - an unreadable PDF falls back to the abstract
        print(f"pdf text failed: {exc}")
        return "", ""
    text = " ".join(text.split())
    if len(text) < 2000:
        return "", ""
    if len(text) > max_chars:
        return text[:max_chars], f"truncated at {max_chars} chars of {len(text)}"
    return text, "full (open-access PDF)"


def fetch_pdf_fulltext(url: str) -> tuple[str, str]:
    if not url:
        return "", ""
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "trading-research-engine"})
        if resp.status_code != 200:
            return "", ""
        return pdf_to_text(resp.content)
    except Exception as exc:  # noqa: BLE001
        print(f"pdf fetch failed for {url}: {exc}")
        return "", ""
