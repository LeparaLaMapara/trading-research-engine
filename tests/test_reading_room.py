"""Reading room: the parts code decides (grounding, ranking, selection, parsing, the queue)."""
from scout import fields, sources
from scout.reading_room import (is_grounded, merge_queue, norm_title, priority, select,
                                verify_quotes)

PAPER = ("We find that the  realised volatility of currency pairs follows a power law with "
         "exponent close to 1.5. The effect weakens after transaction costs of 2 basis points.")


def test_quotes_found_modulo_case_and_whitespace():
    ok, bad = verify_quotes(["the realised volatility of currency pairs follows a POWER law",
                             "The effect weakens after transaction costs of 2 basis points."],
                            PAPER)
    assert len(ok) == 2 and not bad


def test_invented_or_short_quotes_rejected():
    ok, bad = verify_quotes(["volatility of currency pairs follows an exponential law",
                             "power law", 42], PAPER)
    assert not ok and len(bad) == 3


def test_grounding_needs_two_quotes_from_full_text_one_from_abstract():
    assert not is_grounded(1, "full")
    assert is_grounded(2, "full")
    assert is_grounded(1, "abstract")
    assert not is_grounded(0, "abstract")


def test_priority_is_code_not_model():
    assert priority({"information": 4, "value": 5, "cost": 2}) == 10.0
    assert priority({"information": 9, "value": 9, "cost": 1}) == 25.0      # clipped to 5
    assert priority({"information": 4, "value": 5}) == 0.0                  # missing -> 0
    assert priority({"information": "x", "value": 5, "cost": 1}) == 0.0


def test_select_caps_each_field_and_drops_low_scores():
    papers = ([{"title": f"p{i}", "field": "physics", "triage": 5} for i in range(5)]
              + [{"title": "e", "field": "economics", "triage": 4},
                 {"title": "low", "field": "computer science", "triage": 2}])
    got = select(papers, k=8, per_field=3)
    assert [p["field"] for p in got].count("physics") == 3
    assert "e" in [p["title"] for p in got]
    assert "low" not in [p["title"] for p in got]


def test_openalex_abstract_rebuilt_in_order_and_empty_dropped():
    payload = {"results": [
        {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "title": "Carry",
         "abstract_inverted_index": {"carry": [0], "pays": [1], "sometimes": [2]},
         "publication_date": "2026-09-01", "cited_by_count": 3, "authorships": []},
        {"id": "https://openalex.org/W2", "title": "No abstract",
         "abstract_inverted_index": None},
    ]}
    got = sources.parse_openalex(payload)
    assert len(got) == 1
    assert got[0]["abstract"] == "carry pays sometimes"
    assert got[0]["identifier"] == "doi:10.1/x"


def test_arxiv_keyword_clause():
    assert sources.keyword_clause("power law OR criticality") == \
        '(all:"power law" OR all:criticality)'


def test_html_to_text_skips_scripts_keeps_formula_source():
    html = ('<html><script>var x=1</script><p>Price is</p>'
            '<math alttext="x_t"><mi>x</mi></math><p>here.</p></html>')
    assert sources.html_to_text(html) == "Price is $x_t$ here."


def test_every_field_has_a_bridge_question_and_queries():
    for f in fields.FIELDS:
        assert f["bridge"] and f["arxiv"] and f["openalex"]
    names = {f["name"] for f in fields.FIELDS}
    assert {"physics", "economics", "statistics", "mathematics", "computer science"} <= names
    cats = [c for _, c, _ in fields.arxiv_queries()]
    assert len(cats) == len(set(zip(cats, [k for _, _, k in fields.arxiv_queries()])))


def test_queue_merge_statuses_and_order():
    cards = [
        {"id": "W-1", "title": "a", "grounded": True,
         "red_team": {"information": 4, "value": 4, "cost": 2, "kill": False}},
        {"id": "W-2", "title": "b", "grounded": True,
         "red_team": {"information": 5, "value": 5, "cost": 1, "kill": True, "fatal": "costs"}},
        {"id": "W-3", "title": "c", "grounded": False},
        {"id": "W-4", "title": "d", "grounded": True,
         "red_team": {"information": 5, "value": 5, "cost": 1, "kill": False}},
    ]
    q = merge_queue({"updated": None, "items": []}, cards, "W")
    assert [i["id"] for i in q["items"]] == ["W-4", "W-1", "W-2", "W-3"]
    assert q["items"][2]["status"] == "killed" and q["items"][2]["why_killed"] == "costs"
    assert q["items"][3]["status"] == "ungrounded"
    again = merge_queue(q, cards, "W")          # re-merging adds nothing
    assert len(again["items"]) == 4


def test_norm_title_dedupes_formatting():
    assert norm_title("Time-Series Momentum!") == norm_title("time series momentum")


def test_failed_triage_marks_nothing_as_read():
    from scout.reading_room import triage

    class Broke:
        def complete(self, system, user):
            raise RuntimeError("credit balance is too low")

    papers = [{"title": "t", "field": "physics", "abstract": "a"}]
    triage(papers, Broke(), "facts")
    assert papers[0]["triage"] == 0 and not papers[0].get("triaged")


def test_lenient_json_repairs_tex_backslashes_only():
    from scout.reading_room import loads_lenient
    # What a model writes: TeX with single backslashes inside a JSON string.
    assert loads_lenient(r'{"f": "\alpha and \sigma_t"}') == {"f": r"\alpha and \sigma_t"}
    # Already valid escapes are left alone.
    assert loads_lenient(r'{"f": "a \\ b \"q\""}') == {"f": r'a \ b "q"'}


def test_transfer_fields_get_reserved_seats():
    papers = ([{"title": f"q{i}", "field": "quantitative finance", "triage": 5}
               for i in range(3)]
              + [{"title": f"c{i}", "field": "computer science", "triage": 5} for i in range(3)]
              + [{"title": f"e{i}", "field": "economics", "triage": 4} for i in range(3)]
              + [{"title": "phys", "field": "physics", "triage": 2},
                 {"title": "math", "field": "mathematics", "triage": 2},
                 {"title": "stat", "field": "statistics", "triage": 1}])
    got = [p["title"] for p in select(papers, k=8)]
    assert len(got) == 8 and "phys" in got and "math" in got and "stat" not in got


def test_top_venue_breaks_ties_but_never_lifts_irrelevant_papers():
    from scout.reading_room import rank_score
    jf = {"issn": ["0022-1082"], "triage": 3}
    arx = {"issn": [], "triage": 3}
    junk = {"issn": ["0022-1082"], "triage": 1}
    assert rank_score(jf) == 4 and rank_score(arx) == 3 and rank_score(junk) == 1


def test_openalex_keeps_issn():
    payload = {"results": [{"id": "https://openalex.org/W9", "title": "Carry",
                            "abstract_inverted_index": {"carry": [0]},
                            "primary_location": {"source": {"display_name": "Journal of Finance",
                                                            "issn": ["0022-1082", "1540-6261"]}}}]}
    got = sources.parse_openalex(payload)
    assert got[0]["issn"] == ["0022-1082", "1540-6261"] and fields.is_top_venue(got[0])


def test_pdf_text_rejects_web_pages_and_short_text():
    assert sources.pdf_to_text(b"<html>paywall</html>") == ("", "")
    assert sources.pdf_to_text(b"%PDF-1.4 broken") == ("", "")


def test_openalex_records_open_access_pdf():
    payload = {"results": [{"id": "https://openalex.org/W7", "title": "Vol managed",
                            "abstract_inverted_index": {"vol": [0]},
                            "best_oa_location": {"pdf_url": "https://example.org/p.pdf"}}]}
    assert sources.parse_openalex(payload)[0]["oa_pdf"] == "https://example.org/p.pdf"
