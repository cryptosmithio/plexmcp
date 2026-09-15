"""Deep enrichment orchestrator: concurrent fetch, LLM synthesis, cross-refs, persistence."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from ...utils import get_logger
from . import crossref, db
from .sources import fetch_justwatch, fetch_tmdb_deep, fetch_wikipedia
from .synthesis import SampleFn, synthesise_report

logger = get_logger(__name__)

ALL_SOURCES = ("wikipedia", "tmdb", "justwatch")


async def enrich_media_item(
    rating_key: str,
    *,
    title: str,
    year: int | None,
    media_type: str,
    force_refresh: bool = False,
    sources: list[str] | None = None,
    sample_fn: SampleFn | None = None,
    tmdb_api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch from configured sources, synthesise via LLM (if sample_fn given), persist, return the report."""
    if not force_refresh and db.has_fresh_enrichment(rating_key):
        cached = db.load_enrichment(rating_key)
        if cached:
            cached["from_cache"] = True
            return cached

    wanted = set(sources) if sources is not None else set(ALL_SOURCES)
    tasks: dict[str, Any] = {}
    if "wikipedia" in wanted:
        tasks["wikipedia"] = fetch_wikipedia(title, year, media_type)
    if "tmdb" in wanted:
        tasks["tmdb"] = fetch_tmdb_deep(title, year, media_type, tmdb_api_key or os.environ.get("TMDB_API_KEY", ""))
    if "justwatch" in wanted:
        tasks["justwatch"] = fetch_justwatch(title, year, media_type)

    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    raw: dict[str, Any] = {}
    sources_fetched: list[str] = []
    sources_failed: list[str] = []
    for key, result in zip(keys, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("Source %s failed for %s: %s", key, title, result)
            sources_failed.append(key)
        elif result is None:
            sources_failed.append(key)
        else:
            raw[key] = result
            sources_fetched.append(key)

    tmdb_data = raw.get("tmdb") or {}
    director = tmdb_data.get("director")
    cast = tmdb_data.get("cast") or []
    collection_id = tmdb_data.get("collection_id")

    if sample_fn is not None and (raw.get("wikipedia") or raw.get("tmdb")):
        try:
            report, parsed_ok = await synthesise_report(title, year, media_type, raw, sample_fn)
            if not parsed_ok:
                sources_failed.append("synthesis_parse")
        except Exception as e:
            logger.warning("LLM synthesis failed for %s: %s", title, e)
            report = _fallback_report(raw)
            sources_failed.append("synthesis")
    else:
        report = _fallback_report(raw)
        if sample_fn is None:
            sources_failed.append("synthesis_unavailable")

    themes = report.get("thematic_tags") or []
    if not isinstance(themes, list):
        themes = []

    db.save_enrichment(
        rating_key,
        media_type=media_type,
        title=title,
        year=year,
        report_sections=report,
        sources_fetched=sources_fetched,
        sources_failed=sources_failed,
        raw_data=raw,
        themes=themes,
        director=director,
        tmdb_collection_id=collection_id,
    )

    crossref.extract_cross_references(
        rating_key,
        director=director,
        cast=cast,
        themes=themes,
        collection_id=collection_id,
    )

    saved = db.load_enrichment(rating_key)
    saved["from_cache"] = False
    return saved


def _fallback_report(raw: dict[str, Any]) -> dict[str, Any]:
    """No LLM available: surface the raw sources directly instead of a synthesised dossier."""
    wiki = raw.get("wikipedia") or {}
    tmdb = raw.get("tmdb") or {}
    return {
        "synopsis": tmdb.get("overview") or wiki.get("summary", "")[:400],
        "critical_overview": wiki.get("summary") or "",
        "why_this_matters": "",
        "production_notes": "",
        "reception_at_release": "",
        "legacy": "",
        "content_warnings": {"violence": "", "sexual_content": "", "language": "", "other_triggers": []},
        "thematic_tags": tmdb.get("keywords", [])[:7] if tmdb.get("keywords") else [],
        "director_context": "",
        "key_cast_notes": "",
        "awards": [],
        "trivia": [],
    }


def get_related(rating_key: str, relation_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return db.get_cross_refs(rating_key, relation_type=relation_type, limit=limit)


def get_enrichment(rating_key: str) -> dict[str, Any] | None:
    return db.load_enrichment(rating_key)


def search_by_theme(theme: str, limit: int = 50) -> list[dict[str, Any]]:
    return db.search_by_theme(theme, limit=limit)


def search_by_person(name: str, role: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if role and role.lower() != "director":
        return []  # only director is indexed as a column today; cast lives in raw_data only
    return db.search_by_director(name, limit=limit)


def list_stale(days: int = 90, limit: int = 200) -> list[dict[str, Any]]:
    return db.list_stale(days=days, limit=limit)


def count_enriched() -> int:
    return db.count_enriched()
