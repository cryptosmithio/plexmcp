"""Cross-reference extraction between already-enriched library items.

Scoped to compare a newly-enriched item against the set of items already in
the ``media_enrichment`` table (not a live scan of the whole Plex library by
person) — cross-refs grow denser as more of the library gets enriched, same
spirit as the spec's "starts feeling like a graph" goal, without needing a new
Plex-side person index.
"""

from __future__ import annotations

from typing import Any

from . import db


def extract_cross_references(
    rating_key: str,
    director: str | None,
    cast: list[dict[str, Any]],
    themes: list[str],
    collection_id: int | None,
) -> list[dict[str, Any]]:
    """Compute and persist cross-refs for `rating_key` against the enriched set. Returns the refs."""
    others = [o for o in db.all_enriched_summaries() if o["plex_rating_key"] != rating_key]
    refs: list[tuple[str, str, str, float]] = []
    my_themes = {t.strip().lower() for t in themes if t}
    cast_names = {c.get("name") for c in cast[:5] if c.get("name")}

    for other in others:
        other_key = other["plex_rating_key"]

        if director and other.get("director") and other["director"].strip().lower() == director.strip().lower():
            refs.append((other_key, "director", director, 1.0))

        if collection_id is not None and other.get("tmdb_collection_id") == collection_id:
            refs.append((other_key, "same_collection", None, 1.0))

        other_themes = set()
        raw_themes = other.get("themes")
        if isinstance(raw_themes, list):
            other_themes = {str(t).strip().lower() for t in raw_themes if t}
        overlap = my_themes & other_themes
        if len(overlap) >= 2:
            confidence = len(overlap) / max(len(my_themes), 1)
            refs.append((other_key, "thematic", ", ".join(sorted(overlap)), round(confidence, 2)))

        other_raw = other.get("raw_data") or {}
        other_cast = ((other_raw.get("tmdb") or {}).get("cast") or []) if isinstance(other_raw, dict) else []
        other_cast_names = {c.get("name") for c in other_cast[:5] if isinstance(c, dict) and c.get("name")}
        shared = cast_names & other_cast_names
        for name in shared:
            refs.append((other_key, "shared_cast", name, 0.8))

    db.replace_cross_refs(rating_key, refs)
    return db.get_cross_refs(rating_key)
