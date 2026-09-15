"""Tests for the deep enrichment REST API (webapp/backend/app/api/enrichment.py).

mcp_client.call_tool and the source fetchers are mocked - no real Plex/network
calls. The enrichment sqlite DB is redirected to a tmp_path file per test.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from plex_mcp.services.enrichment import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db.set_db_path(tmp_path / "enrichment_api_test.db")
    yield


def _plex_details(rating_key: str, title: str, year: int, media_type: str = "movie"):
    return {"success": True, "data": {"title": title, "year": year, "type": media_type}}


@pytest.mark.asyncio
async def test_enrich_one_success(webapp_app):
    with (
        patch(
            "webapp.backend.app.api.enrichment.mcp_client.call_tool",
            AsyncMock(return_value=_plex_details("1", "Heat", 1995)),
        ),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_wikipedia", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_tmdb_deep", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_justwatch", AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
            response = await ac.post("/api/enrichment/1", json={"sources": []})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["title"] == "Heat"
            assert data["year"] == 1995


@pytest.mark.asyncio
async def test_enrich_one_missing_plex_item_404s(webapp_app):
    with patch(
        "webapp.backend.app.api.enrichment.mcp_client.call_tool",
        AsyncMock(return_value={"success": False, "error": "not found"}),
    ):
        async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
            response = await ac.post("/api/enrichment/999", json={})
            assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_enrichment_report_not_yet_enriched(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.get("/api/enrichment/12345")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] is None


@pytest.mark.asyncio
async def test_get_related_empty_for_unenriched_item(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.get("/api/enrichment/12345/related")
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["count"] == 0


@pytest.mark.asyncio
async def test_literal_routes_not_shadowed_by_rating_key_catchall(webapp_app):
    """Regression test: /by-theme, /by-person, /status/* must resolve, not 'rating_key=by-theme'."""
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        for path in (
            "/api/enrichment/by-theme?theme=heist",
            "/api/enrichment/by-person?name=Someone",
            "/api/enrichment/status/stale",
            "/api/enrichment/status/stats",
        ):
            response = await ac.get(path)
            assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text}"
            assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_bulk_enrich_explicit_rating_keys_completes(webapp_app):
    with (
        patch(
            "webapp.backend.app.api.enrichment.mcp_client.call_tool",
            AsyncMock(side_effect=lambda _name, args: _plex_details(args["media_key"], f"Title {args['media_key']}", 2000)),
        ),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_wikipedia", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_tmdb_deep", AsyncMock(return_value=None)),
        patch("plex_mcp.services.enrichment.orchestrator.fetch_justwatch", AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
            start = await ac.post(
                "/api/enrichment/bulk",
                json={"rating_keys": ["10", "11"], "max_items": 10, "sources": []},
            )
            assert start.status_code == 200
            job_id = start.json()["job_id"]

            for _ in range(50):
                status = await ac.get(f"/api/enrichment/bulk/status/{job_id}")
                body = status.json()
                if body["phase"] != "running":
                    break
                await asyncio.sleep(0.05)

            assert body["phase"] == "complete"
            assert body["done"] == 2
            assert body["failed"] == 0

            stats = await ac.get("/api/enrichment/status/stats")
            assert stats.json()["enriched_count"] == 2


@pytest.mark.asyncio
async def test_bulk_enrich_requires_keys_or_library(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.post("/api/enrichment/bulk", json={})
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_bulk_status_unknown_job_404s(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.get("/api/enrichment/bulk/status/does-not-exist")
        assert response.status_code == 404
