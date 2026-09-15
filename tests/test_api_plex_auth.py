"""Tests for the Plex token test/refresh endpoints (Settings page facility).

Covers webapp/backend/app/api/system.py: POST /plex/test, POST /plex/pin,
GET /plex/pin/{id}. All Plex/plex.tv network calls are mocked; no real
settings.json is touched.
"""

from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

# httpx.AsyncClient.get/post are patched at the class level below, which would
# also intercept the outer ASGITransport-backed test client's own requests
# (it's an AsyncClient too). These wrappers only fake calls to real external
# hosts (plex.tv, a Plex server) — anything targeting the "http://test" ASGI
# test host passes through to the real implementation so the app actually runs.
_real_get = AsyncClient.get
_real_post = AsyncClient.post


def _fake_get(response=None, exc=None):
    async def _get(self, url, *args, **kwargs):
        if str(self.base_url) == "http://test":
            return await _real_get(self, url, *args, **kwargs)
        if exc is not None:
            raise exc
        return response

    return _get


def _fake_post(response):
    async def _post(self, url, *args, **kwargs):
        if str(self.base_url) == "http://test":
            return await _real_post(self, url, *args, **kwargs)
        return response

    return _post


@pytest.mark.asyncio
async def test_plex_test_connection_missing_credentials(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with patch("webapp.backend.app.api.system.os.environ", {}):
            response = await ac.post("/api/system/plex/test", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "required" in data["message"].lower()


@pytest.mark.asyncio
async def test_plex_test_connection_success(webapp_app):
    fake_response = httpx.Response(
        200,
        json={
            "MediaContainer": {
                "friendlyName": "Sandra's Plex",
                "version": "1.42.0",
                "machineIdentifier": "abc123",
            }
        },
    )
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with patch("httpx.AsyncClient.get", _fake_get(response=fake_response)):
            response = await ac.post(
                "/api/system/plex/test",
                json={"plex_url": "http://localhost:32400", "plex_token": "goodtoken"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "Sandra's Plex" in data["message"]
            assert data["data"]["version"] == "1.42.0"


@pytest.mark.asyncio
async def test_plex_test_connection_unauthorized(webapp_app):
    fake_response = httpx.Response(401, json={})
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with patch("httpx.AsyncClient.get", _fake_get(response=fake_response)):
            response = await ac.post(
                "/api/system/plex/test",
                json={"plex_url": "http://localhost:32400", "plex_token": "badtoken"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "401" in data["message"] or "invalid" in data["message"].lower()


@pytest.mark.asyncio
async def test_plex_test_connection_unreachable(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with patch("httpx.AsyncClient.get", _fake_get(exc=httpx.ConnectError("connection refused"))):
            response = await ac.post(
                "/api/system/plex/test",
                json={"plex_url": "http://localhost:32400", "plex_token": "sometoken"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "could not reach" in data["message"].lower()


@pytest.mark.asyncio
async def test_plex_pin_create_success(webapp_app):
    fake_response = httpx.Response(201, json={"id": 12345, "code": "abcd1234"})
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with patch("httpx.AsyncClient.post", _fake_post(fake_response)):
            response = await ac.post("/api/system/plex/pin")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["pin_id"] == 12345
            assert data["data"]["code"] == "abcd1234"
            assert "client_id" in data["data"]
            assert data["data"]["code"] in data["data"]["auth_url"]
            assert data["data"]["client_id"] in data["data"]["auth_url"]


@pytest.mark.asyncio
async def test_plex_pin_poll_pending(webapp_app):
    fake_response = httpx.Response(200, json={"authToken": None})
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with patch("httpx.AsyncClient.get", _fake_get(response=fake_response)):
            response = await ac.get("/api/system/plex/pin/12345", params={"client_id": "deadbeef"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["authorized"] is False


@pytest.mark.asyncio
async def test_plex_pin_poll_authorized_saves_token(webapp_app):
    fake_response = httpx.Response(200, json={"authToken": "freshtoken123"})
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        with (
            patch("httpx.AsyncClient.get", _fake_get(response=fake_response)),
            patch("webapp.backend.app.api.system.save_overrides") as mock_save,
        ):
            response = await ac.get("/api/system/plex/pin/12345", params={"client_id": "deadbeef"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["authorized"] is True
            assert data["data"]["token_set"] is True
            mock_save.assert_called_once_with({"plex_token": "freshtoken123"})
