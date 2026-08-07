"""Real research sources for the Scout. No fabrication: everything here FETCHES.

arXiv is the primary source: free, no API key, and every result carries a resolvable
identifier (the arXiv id) plus the real abstract text. The anti-hallucination rule (spec
§5) is enforced upstream by only ever handing the LLM text that was actually fetched here.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

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
