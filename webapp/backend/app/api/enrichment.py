"""Deep media enrichment REST API: single-item dossier, bulk jobs, theme/person search.

Route order matters here: FastAPI/Starlette match path templates in registration
order, and `/{rating_key}` is a single-segment catch-all. Every literal path
(`/bulk`, `/by-theme`, `/by-person`, `/status/*`) MUST be registered before the
generic `/{rating_key}` GET/POST routes below, or it gets shadowed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from .. import enrichment_jobs
from ..mcp.client import mcp_client
from ..utils.errors import handle_mcp_error

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_BULK_ITEMS = 500


class EnrichRequest(BaseModel):
    force_refresh: bool = False
    sources: list[str] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class BulkEnrichRequest(BaseModel):
    library_id: str | None = None
    rating_keys: list[str] | None = None
    max_items: int = 50
    force_refresh: bool = False
    sources: list[str] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


def _make_sample_fn(llm_provider: str | None, llm_model: str | None):
    """Adapt the webapp's LLM provider registry to the enrichment synthesis seam."""
    if not llm_provider or not llm_model:
        return None

    from .. import llm_providers as lp

    async def _sample(system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await lp.chat_complete(llm_provider, llm_model, messages)

    return _sample


async def _resolve_plex_meta(rating_key: str) -> dict[str, Any]:
    result = await mcp_client.call_tool("plex_media", {"operation": "get_details", "media_key": rating_key})
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=str(result.get("error") or "Media not found"))
    data = result.get("data")
    if not data or not isinstance(data, dict):
        raise HTTPException(status_code=404, detail="No metadata returned")
    title = str(data.get("title") or data.get("name") or "").strip() or "Unknown"
    raw_year = data.get("year")
    try:
        year = int(raw_year) if raw_year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    mtype = str(data.get("type") or "movie").lower()
    media_type = "show" if mtype in ("show", "series") else "movie"
    return {"title": title, "year": year, "media_type": media_type}


# --- Literal-path routes first (see module docstring) -----------------------


async def _run_bulk_job(job_id: str, rating_keys: list[str], body: BulkEnrichRequest) -> None:
    from plex_mcp.services.enrichment.orchestrator import enrich_media_item

    sample_fn = _make_sample_fn(body.llm_provider, body.llm_model)
    semaphore = asyncio.Semaphore(3)

    async def _one(rk: str) -> None:
        async with semaphore:
            try:
                plex_meta = await _resolve_plex_meta(rk)
                await enrich_media_item(
                    rk,
                    title=plex_meta["title"],
                    year=plex_meta["year"],
                    media_type=plex_meta["media_type"],
                    force_refresh=body.force_refresh,
                    sources=body.sources,
                    sample_fn=sample_fn,
                )
                enrichment_jobs.record_item(job_id, ok=True, title=plex_meta["title"])
            except Exception as e:
                logger.warning("Bulk enrichment failed for %s: %s", rk, e)
                enrichment_jobs.record_item(job_id, ok=False, title=rk, error=str(e))

    try:
        await asyncio.gather(*[_one(rk) for rk in rating_keys])
        enrichment_jobs.finish_job(job_id)
    except Exception as e:
        logger.exception("Bulk enrichment job failed")
        enrichment_jobs.fail_job(job_id, str(e))


@router.post("/bulk")
async def start_bulk_enrich(body: BulkEnrichRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Queue a background enrichment run over rating_keys or every item in a library."""
    if enrichment_jobs.active_job_id():
        raise HTTPException(status_code=409, detail="A bulk enrichment job is already running.")

    rating_keys = list(body.rating_keys or [])
    if not rating_keys:
        if not body.library_id:
            raise HTTPException(status_code=400, detail="Provide rating_keys or library_id.")
        result = await mcp_client.call_tool(
            "plex_media", {"operation": "browse", "library_id": body.library_id, "limit": body.max_items}
        )
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=str(result.get("error") or "Could not browse library"))
        items = result.get("data") or []
        rating_keys = [str(i.get("id") or i.get("ratingKey")) for i in items if i.get("id") or i.get("ratingKey")]

    rating_keys = rating_keys[: min(body.max_items, MAX_BULK_ITEMS)]
    if not rating_keys:
        raise HTTPException(status_code=400, detail="No items resolved to enrich.")

    job_id = enrichment_jobs.start_job(total=len(rating_keys))
    background_tasks.add_task(_run_bulk_job, job_id, rating_keys, body)
    return {"success": True, "job_id": job_id, "total": len(rating_keys)}


@router.get("/bulk/status/{job_id}")
async def get_bulk_status(job_id: str) -> dict[str, Any]:
    job = enrichment_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {"success": True, **job}


@router.get("/by-theme")
async def by_theme(theme: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    from plex_mcp.services.enrichment.orchestrator import search_by_theme

    hits = search_by_theme(theme, limit=limit)
    return {"success": True, "data": hits, "count": len(hits)}


@router.get("/by-person")
async def by_person(
    name: str = Query(..., min_length=1), role: str | None = Query(None), limit: int = Query(50, ge=1, le=200)
) -> dict[str, Any]:
    from plex_mcp.services.enrichment.orchestrator import search_by_person

    hits = search_by_person(name, role=role, limit=limit)
    return {"success": True, "data": hits, "count": len(hits)}


@router.get("/status/stale")
async def stale(days: int = Query(90, ge=1), limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    from plex_mcp.services.enrichment.orchestrator import list_stale

    hits = list_stale(days=days, limit=limit)
    return {"success": True, "data": hits, "count": len(hits)}


@router.get("/status/stats")
async def stats() -> dict[str, Any]:
    from plex_mcp.services.enrichment.orchestrator import count_enriched

    return {
        "success": True,
        "enriched_count": count_enriched(),
        "active_job_id": enrichment_jobs.active_job_id(),
    }


# --- Generic /{rating_key} routes MUST come last -----------------------------


@router.post("/{rating_key}")
async def enrich_one(rating_key: str, body: EnrichRequest) -> dict[str, Any]:
    """Fetch/synthesise the deep dossier for one library item (cached 90 days)."""
    from plex_mcp.services.enrichment.orchestrator import enrich_media_item

    try:
        plex_meta = await _resolve_plex_meta(rating_key)
        sample_fn = _make_sample_fn(body.llm_provider, body.llm_model)
        report = await enrich_media_item(
            rating_key,
            title=plex_meta["title"],
            year=plex_meta["year"],
            media_type=plex_meta["media_type"],
            force_refresh=body.force_refresh,
            sources=body.sources,
            sample_fn=sample_fn,
        )
        return {"success": True, **report}
    except HTTPException:
        raise
    except Exception as e:
        raise handle_mcp_error(e) from e


@router.get("/{rating_key}/related")
async def get_related_items(
    rating_key: str,
    relation_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    from plex_mcp.services.enrichment.orchestrator import get_related

    related = get_related(rating_key, relation_type=relation_type, limit=limit)
    return {"success": True, "data": related, "count": len(related)}


@router.get("/{rating_key}")
async def get_enrichment_report(rating_key: str) -> dict[str, Any]:
    from plex_mcp.services.enrichment.orchestrator import get_enrichment

    report = get_enrichment(rating_key)
    if not report:
        return {"success": True, "data": None, "message": "Not yet enriched."}
    return {"success": True, "data": report}
