"""Unit tests for the deep enrichment service layer (db, crossref, synthesis, orchestrator).

No real network calls: source fetchers are monkeypatched. The sqlite DB is
redirected to a tmp_path file per test so nothing touches the real
data/enrichment.db.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from plex_mcp.services.enrichment import crossref, db, orchestrator
from plex_mcp.services.enrichment.synthesis import build_user_prompt, parse_report


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db.set_db_path(tmp_path / "enrichment_test.db")
    yield


# --- db.py --------------------------------------------------------------


def test_save_and_load_roundtrip():
    db.save_enrichment(
        "1",
        media_type="movie",
        title="Heat",
        year=1995,
        report_sections={"synopsis": "A heist film."},
        sources_fetched=["wikipedia"],
        sources_failed=[],
        raw_data={"tmdb": {"director": "Michael Mann"}},
        themes=["heist"],
        director="Michael Mann",
        tmdb_collection_id=None,
    )
    loaded = db.load_enrichment("1")
    assert loaded["title"] == "Heat"
    assert loaded["report_sections"]["synopsis"] == "A heist film."
    assert loaded["themes"] == ["heist"]
    assert db.has_fresh_enrichment("1") is True
    assert db.count_enriched() == 1


def test_has_fresh_enrichment_false_for_unknown_key():
    assert db.has_fresh_enrichment("nonexistent") is False


def test_upsert_bumps_version():
    db.save_enrichment(
        "1",
        media_type="movie",
        title="Heat",
        year=1995,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={},
        themes=[],
        director=None,
        tmdb_collection_id=None,
    )
    db.save_enrichment(
        "1",
        media_type="movie",
        title="Heat",
        year=1995,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={},
        themes=[],
        director=None,
        tmdb_collection_id=None,
    )
    loaded = db.load_enrichment("1")
    assert loaded["enrichment_version"] == 2


def test_search_by_theme_and_director():
    db.save_enrichment(
        "1",
        media_type="movie",
        title="Heat",
        year=1995,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={},
        themes=["heist", "existential"],
        director="Michael Mann",
        tmdb_collection_id=None,
    )
    assert [r["title"] for r in db.search_by_theme("heist")] == ["Heat"]
    assert [r["title"] for r in db.search_by_theme("nope")] == []
    assert [r["title"] for r in db.search_by_director("Michael Mann")] == ["Heat"]
    assert [r["title"] for r in db.search_by_director("Someone Else")] == []


# --- crossref.py ----------------------------------------------------------


def test_crossref_director_match():
    db.save_enrichment(
        "1",
        media_type="movie",
        title="Heat",
        year=1995,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={"tmdb": {"cast": []}},
        themes=[],
        director="Michael Mann",
        tmdb_collection_id=None,
    )
    db.save_enrichment(
        "2",
        media_type="movie",
        title="Collateral",
        year=2004,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={"tmdb": {"cast": []}},
        themes=[],
        director="Michael Mann",
        tmdb_collection_id=None,
    )
    refs = crossref.extract_cross_references("1", director="Michael Mann", cast=[], themes=[], collection_id=None)
    assert any(r["target_rating_key"] == "2" and r["relation_type"] == "director" for r in refs)


def test_crossref_thematic_needs_two_shared_tags():
    db.save_enrichment(
        "1",
        media_type="movie",
        title="A",
        year=2000,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={},
        themes=["heist", "noir"],
        director=None,
        tmdb_collection_id=None,
    )
    db.save_enrichment(
        "2",
        media_type="movie",
        title="B",
        year=2001,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={},
        themes=["heist"],
        director=None,
        tmdb_collection_id=None,
    )
    refs = crossref.extract_cross_references("1", director=None, cast=[], themes=["heist", "noir"], collection_id=None)
    assert refs == []  # only 1 shared tag ("heist") - below the >=2 threshold

    db.save_enrichment(
        "3",
        media_type="movie",
        title="C",
        year=2002,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={},
        themes=["heist", "noir"],
        director=None,
        tmdb_collection_id=None,
    )
    refs2 = crossref.extract_cross_references("1", director=None, cast=[], themes=["heist", "noir"], collection_id=None)
    assert any(r["target_rating_key"] == "3" and r["relation_type"] == "thematic" for r in refs2)


def test_crossref_shared_cast():
    db.save_enrichment(
        "1",
        media_type="movie",
        title="A",
        year=2000,
        report_sections={},
        sources_fetched=[],
        sources_failed=[],
        raw_data={"tmdb": {"cast": [{"name": "Al Pacino"}]}},
        themes=[],
        director=None,
        tmdb_collection_id=None,
    )
    refs = crossref.extract_cross_references(
        "2", director=None, cast=[{"name": "Al Pacino"}], themes=[], collection_id=None
    )
    assert any(r["target_rating_key"] == "1" and r["relation_type"] == "shared_cast" for r in refs)


# --- synthesis.py -----------------------------------------------------------


def test_parse_report_valid_json():
    raw = json.dumps({"synopsis": "S", "thematic_tags": ["a", "b"]})
    report, ok = parse_report(raw)
    assert ok is True
    assert report["synopsis"] == "S"
    assert report["thematic_tags"] == ["a", "b"]
    assert report["awards"] == ""  # missing key defaults to empty string, not KeyError


def test_parse_report_strips_code_fences():
    raw = "```json\n" + json.dumps({"synopsis": "S"}) + "\n```"
    report, ok = parse_report(raw)
    assert ok is True
    assert report["synopsis"] == "S"


def test_parse_report_invalid_json_falls_back():
    report, ok = parse_report("not json at all, just prose")
    assert ok is False
    assert "not json at all" in report["critical_overview"]
    assert report["thematic_tags"] == []


def test_build_user_prompt_includes_title_and_sources():
    prompt = build_user_prompt("Heat", 1995, "movie", {"wikipedia": {"summary": "..."}})
    assert "Heat" in prompt
    assert "1995" in prompt
    assert "wikipedia" in prompt


# --- orchestrator.py --------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_media_item_uses_cache_on_second_call():
    async def fake_sample(system_prompt, user_prompt):
        return json.dumps({"synopsis": "S", "thematic_tags": ["x", "y"]})

    with (
        patch("plex_mcp.services.enrichment.orchestrator.fetch_wikipedia", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_tmdb_deep", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_justwatch", AsyncMock(return_value=None)),
    ):
        report1 = await orchestrator.enrich_media_item(
            "1", title="Heat", year=1995, media_type="movie", sample_fn=fake_sample
        )
        assert report1["from_cache"] is False

        report2 = await orchestrator.enrich_media_item(
            "1", title="Heat", year=1995, media_type="movie", sample_fn=fake_sample
        )
        assert report2["from_cache"] is True


@pytest.mark.asyncio
async def test_enrich_media_item_empty_sources_list_means_no_sources():
    """Regression test: sources=[] must mean 'fetch nothing', not 'fetch everything'."""
    called = {"wiki": False, "tmdb": False, "jw": False}

    async def _wiki(*a, **k):
        called["wiki"] = True
        return

    async def _tmdb(*a, **k):
        called["tmdb"] = True
        return

    async def _jw(*a, **k):
        called["jw"] = True
        return

    with (
        patch("plex_mcp.services.enrichment.orchestrator.fetch_wikipedia", _wiki),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_tmdb_deep", _tmdb),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_justwatch", _jw),
    ):
        await orchestrator.enrich_media_item("1", title="Heat", year=1995, media_type="movie", sources=[])

    assert called == {"wiki": False, "tmdb": False, "jw": False}


@pytest.mark.asyncio
async def test_enrich_media_item_no_sample_fn_falls_back_gracefully():
    async def _wiki(*a, **k):
        return {"summary": "A ballet.", "url": "https://en.wikipedia.org/wiki/X"}

    with (
        patch("plex_mcp.services.enrichment.orchestrator.fetch_wikipedia", _wiki),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_tmdb_deep", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_justwatch", AsyncMock(return_value=None)),
    ):
        report = await orchestrator.enrich_media_item(
            "1", title="Nutcracker", year=1977, media_type="movie", sources=["wikipedia"], sample_fn=None
        )
    assert "synthesis_unavailable" in report["sources_failed"]
    assert report["report_sections"]["critical_overview"] == "A ballet."


@pytest.mark.asyncio
async def test_enrich_media_item_synthesis_failure_falls_back_not_raises():
    async def _boom(system_prompt, user_prompt):
        raise RuntimeError("LLM unreachable")

    with (
        patch("plex_mcp.services.enrichment.orchestrator.fetch_wikipedia", AsyncMock(return_value={"summary": "S"})),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_tmdb_deep", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_justwatch", AsyncMock(return_value=None)),
    ):
        report = await orchestrator.enrich_media_item(
            "1", title="X", year=None, media_type="movie", sources=["wikipedia"], sample_fn=_boom
        )
    assert "synthesis" in report["sources_failed"]
