"""retrieve_documents — the relevance floor (2026-07-27).

Regression for the 2026-07-18 bug: a k=8 over a small corpus pulled a *community-solar* section into a
*green-roofs* brief because it shared the single term "urban" (score 0.33). A 0.5 relevance floor excludes
weak matches; a plan can still override via `min_score`.
"""

from __future__ import annotations

from app.tools.retrieve import MIN_RELEVANCE, _handler, get_tool


def _ids(res):
    return {d["id"] for d in res["documents"]}


def test_relevance_floor_excludes_a_single_shared_term_match():
    # "urban green roofs": the 4 green-roof docs score 1.0; a solar doc matches only "urban" (0.33).
    res = _handler({"query": "urban green roofs", "k": 8})
    ids = _ids(res)
    assert all(i.startswith("doc-greenroof") for i in ids)      # no community-solar leakage
    assert not any(i.startswith("doc-solar") for i in ids)
    assert all(d["score"] >= MIN_RELEVANCE for d in res["documents"])


def test_min_score_is_overridable_to_restore_weak_matches():
    # Opt back into weak matches with an explicit floor of 0 — the solar doc (0.33) reappears.
    res = _handler({"query": "urban green roofs", "k": 8, "min_score": 0.0})
    assert any(i.startswith("doc-solar") for i in _ids(res))


def test_off_corpus_query_returns_nothing():
    res = _handler({"query": "quarterly tax depreciation schedules", "k": 5})
    assert res["documents"] == []


def test_on_topic_query_still_returns_its_documents():
    res = _handler({"query": "community solar equity", "k": 5})
    ids = _ids(res)
    assert ids and all(i.startswith("doc-solar") for i in ids)  # relevant docs still come back


def test_tool_advertises_min_score():
    tool = get_tool()
    assert "min_score" in tool.input_schema["properties"]
    assert "relevance floor" in tool.description
