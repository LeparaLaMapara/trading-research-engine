"""Scout: arXiv parsing, method->strategy mapping, and the anti-hallucination guarantee."""
from council.backends import MockBackend
from research.cards import CardStore
from scout import sources
from scout.scout import Scout, _heuristic_kind

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v1</id>
    <title>Time series momentum in currency markets</title>
    <summary>We document trend following and momentum across FX pairs.</summary>
    <published>2024-01-05T00:00:00Z</published>
    <author><name>A. Researcher</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.05678v2</id>
    <title>Short-horizon mean reversion</title>
    <summary>Prices show contrarian reversal at intraday horizons.</summary>
    <published>2024-02-10T00:00:00Z</published>
    <author><name>B. Scholar</name></author>
  </entry>
</feed>"""


def test_parse_arxiv_atom():
    papers = sources.parse_arxiv_atom(_ATOM)
    assert len(papers) == 2
    assert papers[0]["identifier"] == "arXiv:2401.01234v1"
    assert papers[0]["url"] == "http://arxiv.org/abs/2401.01234v1"
    assert "momentum" in papers[0]["abstract"].lower()


def test_heuristic_mapping():
    assert _heuristic_kind("time series momentum and trend following") == "ma_trend"
    assert _heuristic_kind("intraday mean reversion / reversal") == "mean_reversion"
    assert _heuristic_kind("a volatility target sizing scheme") == "vol_scaled"
    assert _heuristic_kind("a paper about tax policy") is None


def test_card_from_paper_never_fabricates_identifier():
    # With the mock backend (no LLM), the card is still grounded in the FETCHED paper:
    # identifier is the real arXiv id, the abstract is stored, and mapping uses the heuristic.
    paper = sources.parse_arxiv_atom(_ATOM)[0]
    card = Scout(backend=MockBackend())._card_from_paper(paper)
    assert card.identifier == "arXiv:2401.01234v1"      # the fetched id, not invented
    assert card.abstract == paper["abstract"]            # fetched text stored
    assert card.mapped_kind == "ma_trend"


def test_offline_cards_are_marked_not_fabricated():
    for c in Scout(backend=MockBackend()).transfer_cards(3):
        assert c.identifier == "MOCK-OFFLINE"            # never a resolvable-looking fake


def test_card_store_roundtrip(tmp_path):
    store = CardStore(str(tmp_path / "r.db"))
    card = Scout(backend=MockBackend())._card_from_paper(sources.parse_arxiv_atom(_ATOM)[1])
    store.save(card, created_ts=1.0)
    assert store.count() == 1
    row = store.all()[0]
    assert row["identifier"] == "arXiv:2402.05678v2"
    assert row["mapped_kind"] == "mean_reversion"
    store.close()
