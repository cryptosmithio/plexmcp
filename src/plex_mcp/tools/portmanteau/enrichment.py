"""
Plex Media Enrichment Portmanteau Tool (FastMCP 3.1)

Consolidates external metadata discovery, deep multi-source enrichment
(Wikipedia + TMDB + JustWatch, LLM-synthesised critical dossier), and
library-wide cross-referencing (by director, cast, collection, theme).
"""

from typing import Annotated, Any, Literal

from fastmcp import Context
from fastmcp.tools import ToolResult
from pydantic import Field

from ...app import mcp
from ...services.enrichment.orchestrator import enrich_media_item, get_related
from ...services.enrichment.orchestrator import get_enrichment as _get_enrichment
from ...services.enrichment.orchestrator import list_stale as _list_stale
from ...services.enrichment.orchestrator import search_by_person as _search_by_person
from ...services.enrichment.orchestrator import search_by_theme as _search_by_theme
from ...services.enrichment_service import get_enrichment_service
from ...utils import get_logger

logger = get_logger(__name__)


def _get_plex_service():
    import os

    from ...services.plex_service import PlexService

    base_url = os.getenv("PLEX_URL") or os.getenv("PLEX_SERVER_URL", "http://localhost:32400")
    token = os.getenv("PLEX_TOKEN")
    if not token:
        raise RuntimeError("PLEX_TOKEN environment variable is required.")
    return PlexService(base_url=base_url, token=token)


def _make_sample_fn(context: Context | None):
    """Adapt FastMCP Context.sample to the (system_prompt, user_prompt) -> str shape."""
    if context is None or not hasattr(context, "sample"):
        return None

    async def _sample(system_prompt: str, user_prompt: str) -> str:
        result = await context.sample(user_prompt, system_prompt=system_prompt, max_tokens=3000)
        return getattr(result, "text", None) or str(result)

    return _sample


async def _resolve_plex_item(rating_key: str) -> dict[str, Any]:
    plex = _get_plex_service()
    details = await plex.get_media_info(rating_key)
    if not details:
        raise ValueError(f"No Plex item found for rating_key={rating_key}")
    d = details if isinstance(details, dict) else (details.model_dump() if hasattr(details, "model_dump") else {})
    title = str(d.get("title") or d.get("name") or "").strip()
    raw_year = d.get("year")
    try:
        year = int(raw_year) if raw_year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    mtype = str(d.get("type") or "movie").lower()
    media_type = "show" if mtype in ("show", "series") else "movie"
    return {"title": title, "year": year, "media_type": media_type}


@mcp.tool(version="1.1.0", annotations={"readOnlyHint": False, "destructiveHint": False})
async def plex_media_enrichment(
    operation: Annotated[
        Literal[
            "enrich_item",
            "get_external_metadata",
            "analyze_trends",
            "enrich",
            "bulk_enrich",
            "get_enrichment",
            "get_related",
            "search_by_theme",
            "search_by_person",
            "stale_report",
        ],
        Field(description="Operation to perform."),
    ],
    title: Annotated[str | None, Field(description="Title of the media item (for title-only operations).")] = None,
    year: Annotated[int | None, Field(description="Release year of the item.")] = None,
    media_type: Annotated[
        Literal["movie", "show"],
        Field(description="Type of media."),
    ] = "movie",
    rating_key: Annotated[
        str | None,
        Field(description="Plex rating key, for library-item operations (enrich, get_enrichment, get_related)."),
    ] = None,
    rating_keys: Annotated[
        list[str] | None, Field(description="Plex rating keys for bulk_enrich (max 25 per call).")
    ] = None,
    force_refresh: Annotated[bool, Field(description="Bypass the 90-day cache and re-fetch/re-synthesise.")] = False,
    sources: Annotated[
        list[str] | None, Field(description="Restrict to these sources: wikipedia, tmdb, justwatch. Default: all.")
    ] = None,
    relation_type: Annotated[
        str | None, Field(description="Filter get_related: director, shared_cast, same_collection, thematic.")
    ] = None,
    theme: Annotated[str | None, Field(description="Thematic tag to search for (search_by_theme).")] = None,
    person_name: Annotated[str | None, Field(description="Person name to search for (search_by_person).")] = None,
    role: Annotated[str | None, Field(description="Role filter for search_by_person, e.g. 'director'.")] = None,
    days: Annotated[int, Field(description="Age threshold in days for stale_report.")] = 90,
    limit: Annotated[int, Field(description="Max results for list-style operations.", ge=1, le=200)] = 50,
    context: Annotated[
        Context | None, Field(description="FastMCP Context - enables LLM synthesis via ctx.sample when available.")
    ] = None,
) -> ToolResult:
    """High-value media enrichment: Wikipedia/TMDB quick lookups, and a deep,
    LLM-synthesised critical dossier (enrich) with library cross-references.

    PORTMANTEAU PATTERN RATIONALE:
    Consolidates external metadata discovery and deep enrichment into one interface.

    ## Return Format
    {"success": bool, "data": ..., "message": str}

    ## Examples
    await plex_media_enrichment(operation="enrich_item", title="Inception", year=2010)
    await plex_media_enrichment(operation="enrich", rating_key="12345")
    await plex_media_enrichment(operation="get_related", rating_key="12345", relation_type="director")
    await plex_media_enrichment(operation="search_by_theme", theme="heist")
    """
    enrich_service = get_enrichment_service()

    try:
        if operation == "enrich_item":
            if not title:
                return ToolResult(
                    content={"success": False, "error": "title is required", "error_code": "MISSING_TITLE"}
                )
            logger.info(f"Enriching {media_type}: {title} ({year})")
            wiki = await enrich_service.fetch_wikipedia_summary(title, year, media_type)

            if not wiki or not (wiki.get("summary") or "").strip():
                return ToolResult(
                    content={
                        "success": True,
                        "data": f"### High-Value Enrichment: {title}\n\nNo Wikipedia article summary matched this title/year. Try adjusting the year or use get_external_metadata for search links.",
                    }
                )

            extract = (wiki.get("summary") or "").strip()
            page_url = wiki.get("url") or ""
            markdown = f"""
### High-Value context: {title} ({year if year else "N/A"})

**Source:** {wiki.get("source", "Wikipedia")}
**Article:** {page_url}

{extract}

---
> Tip: Use operation="enrich" with a rating_key for a full LLM-synthesised critical dossier and library cross-references.
"""
            return ToolResult(content={"success": True, "data": markdown})

        if operation == "get_external_metadata":
            if not title:
                return ToolResult(
                    content={"success": False, "error": "title is required", "error_code": "MISSING_TITLE"}
                )
            markdown = f"""
### External Discovery: {title}

| Source | Status | Link |
| :--- | :--- | :--- |
| Wikipedia | Found | [View Article](https://en.wikipedia.org/wiki/{title.replace(" ", "_")}) |
| TMDB | Linked | [Direct Search](https://www.themoviedb.org/search?query={title.replace(" ", "%20")}) |
| TV Tropes | Staged | [Direct Search](https://tvtropes.org/pmwiki/search_result.php?q={title.replace(" ", "+")}) |

> [!NOTE]
> Detailed ID mapping (TMDB_ID, TVDB_ID) is available via the enriched RAG index for indexed items.
"""
            return ToolResult(content={"success": True, "data": markdown})

        if operation == "analyze_trends":
            return ToolResult(
                content={
                    "success": True,
                    "data": f"### [MOCK] Cultural Analysis: {title}\n\nCultural trend analysis is currently in alpha.",
                }
            )

        if operation == "enrich":
            if not rating_key:
                return ToolResult(
                    content={"success": False, "error": "rating_key is required", "error_code": "MISSING_RATING_KEY"}
                )
            plex_meta = await _resolve_plex_item(rating_key)
            report = await enrich_media_item(
                rating_key,
                title=plex_meta["title"],
                year=plex_meta["year"],
                media_type=plex_meta["media_type"],
                force_refresh=force_refresh,
                sources=sources,
                sample_fn=_make_sample_fn(context),
            )
            return ToolResult(content={"success": True, "data": report})

        if operation == "bulk_enrich":
            if not rating_keys:
                return ToolResult(
                    content={"success": False, "error": "rating_keys is required", "error_code": "MISSING_RATING_KEYS"}
                )
            capped = rating_keys[:25]
            sample_fn = _make_sample_fn(context)
            done: list[dict[str, Any]] = []
            failed: list[dict[str, str]] = []
            for rk in capped:
                try:
                    plex_meta = await _resolve_plex_item(rk)
                    report = await enrich_media_item(
                        rk,
                        title=plex_meta["title"],
                        year=plex_meta["year"],
                        media_type=plex_meta["media_type"],
                        force_refresh=force_refresh,
                        sources=sources,
                        sample_fn=sample_fn,
                    )
                    done.append({"rating_key": rk, "title": plex_meta["title"]})
                    _ = report
                except Exception as e:
                    failed.append({"rating_key": rk, "error": str(e)})
            return ToolResult(
                content={
                    "success": True,
                    "data": {
                        "enriched": done,
                        "failed": failed,
                        "requested": len(rating_keys),
                        "processed": len(capped),
                    },
                    "message": (
                        f"Bulk-enriched {len(done)}/{len(capped)} item(s)."
                        + (f" {len(rating_keys) - 25} skipped (per-call cap 25)." if len(rating_keys) > 25 else "")
                    ),
                }
            )

        if operation == "get_enrichment":
            if not rating_key:
                return ToolResult(
                    content={"success": False, "error": "rating_key is required", "error_code": "MISSING_RATING_KEY"}
                )
            report = _get_enrichment(rating_key)
            if not report:
                return ToolResult(
                    content={"success": True, "data": None, "message": "No enrichment on file yet for this item."}
                )
            return ToolResult(content={"success": True, "data": report})

        if operation == "get_related":
            if not rating_key:
                return ToolResult(
                    content={"success": False, "error": "rating_key is required", "error_code": "MISSING_RATING_KEY"}
                )
            related = get_related(rating_key, relation_type=relation_type, limit=limit)
            return ToolResult(content={"success": True, "data": related, "count": len(related)})

        if operation == "search_by_theme":
            if not theme:
                return ToolResult(
                    content={"success": False, "error": "theme is required", "error_code": "MISSING_THEME"}
                )
            hits = _search_by_theme(theme, limit=limit)
            return ToolResult(content={"success": True, "data": hits, "count": len(hits)})

        if operation == "search_by_person":
            if not person_name:
                return ToolResult(
                    content={"success": False, "error": "person_name is required", "error_code": "MISSING_PERSON_NAME"}
                )
            hits = _search_by_person(person_name, role=role, limit=limit)
            return ToolResult(content={"success": True, "data": hits, "count": len(hits)})

        if operation == "stale_report":
            hits = _list_stale(days=days, limit=limit)
            return ToolResult(content={"success": True, "data": hits, "count": len(hits)})

        return ToolResult(
            content={
                "success": False,
                "error": f"Unsupported operation '{operation}'",
                "error_code": "INVALID_OPERATION",
            }
        )

    except Exception as e:
        logger.exception("Enrichment error")
        return ToolResult(
            content={"success": False, "error": f"Error performing enrichment: {e}", "error_code": "ENRICHMENT_ERROR"}
        )
