"""Tests for the local+cloud LLM provider registry (webapp/backend/app/llm_providers.py)
and its REST endpoints. Cloud network calls are mocked; the key store is
redirected to a temp file so these tests never touch the real keystore.
"""

from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from webapp.backend.app import llm_providers as lp


@pytest.fixture
def temp_keystore(tmp_path):
    """Redirect the keystore to a throwaway file for the duration of a test."""
    fake_path = tmp_path / "llm_keys.json"
    with patch("webapp.backend.app.llm_providers.keystore_path", return_value=fake_path):
        yield fake_path


def test_public_provider_info_never_leaks_keys(temp_keystore):
    lp.save_key("anthropic", "sk-ant-real-secret")
    info = lp.public_provider_info()
    dumped = str(info)
    assert "sk-ant-real-secret" not in dumped
    anthropic = next(p for p in info if p["id"] == "anthropic")
    assert anthropic["configured"] is True
    assert anthropic["kind"] == "cloud"


def test_local_providers_always_configured(temp_keystore):
    info = lp.public_provider_info()
    for row in info:
        if row["kind"] == "local":
            assert row["configured"] is True


def test_save_and_delete_key_roundtrip(temp_keystore):
    assert lp.is_configured("deepseek") is False
    lp.save_key("deepseek", "sk-test-123")
    assert lp.is_configured("deepseek") is True
    assert lp.get_key("deepseek") == "sk-test-123"
    deleted = lp.delete_key("deepseek")
    assert deleted is True
    assert lp.is_configured("deepseek") is False


def test_save_key_rejects_local_provider(temp_keystore):
    with pytest.raises(ValueError, match="takes no API key"):
        lp.save_key("ollama", "irrelevant")


def test_save_key_rejects_empty(temp_keystore):
    with pytest.raises(ValueError, match="Empty API key"):
        lp.save_key("openai", "   ")


def test_require_provider_unknown_id():
    with pytest.raises(ValueError, match="Unknown provider"):
        lp.require_provider("not-a-real-provider")


@pytest.mark.asyncio
async def test_list_provider_models_cloud_curated_without_key(temp_keystore):
    result = await lp.list_provider_models("anthropic")
    assert result["source"] == "curated"
    assert "claude-sonnet-5" in result["models"]


@pytest.mark.asyncio
async def test_chat_complete_cloud_without_key_raises(temp_keystore):
    with pytest.raises(ValueError, match="no API key configured"):
        await lp.chat_complete("anthropic", "claude-sonnet-5", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_complete_anthropic_format(temp_keystore):
    lp.save_key("anthropic", "sk-ant-test")
    fake_response = httpx.Response(
        200,
        json={"content": [{"type": "text", "text": "Hello there."}]},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    with patch("httpx.AsyncClient.post", return_value=fake_response):
        text = await lp.chat_complete("anthropic", "claude-sonnet-5", [{"role": "user", "content": "hi"}])
    assert text == "Hello there."


def test_gpu_vram_never_raises_without_nvidia_smi():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert lp.gpu_vram() == []


@pytest.mark.asyncio
async def test_ollama_loaded_engine_down():
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("refused")):
        result = await lp.ollama_loaded("http://127.0.0.1:11434")
    assert result == {"engine": False, "models": []}


# --- REST endpoints -----------------------------------------------------


@pytest.mark.asyncio
async def test_providers_endpoint(webapp_app, temp_keystore):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.get("/api/llm/providers")
        assert response.status_code == 200
        data = response.json()
        ids = {p["id"] for p in data["providers"]}
        assert {"ollama", "lmstudio", "vllm", "openai", "anthropic", "deepseek", "openrouter"} <= ids


@pytest.mark.asyncio
async def test_save_and_delete_key_endpoints(webapp_app, temp_keystore):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        save_resp = await ac.post("/api/llm/keys/openrouter", json={"api_key": "sk-or-test"})
        assert save_resp.status_code == 200
        assert save_resp.json()["success"] is True

        providers_resp = await ac.get("/api/llm/providers")
        openrouter = next(p for p in providers_resp.json()["providers"] if p["id"] == "openrouter")
        assert openrouter["configured"] is True

        delete_resp = await ac.delete("/api/llm/keys/openrouter")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_onboarding_endpoint(webapp_app, temp_keystore):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.get("/api/llm/onboarding")
        assert response.status_code == 200
        data = response.json()
        assert "locals" in data
        assert "recommendation" in data


@pytest.mark.asyncio
async def test_gpus_endpoint_never_errors(webapp_app):
    async with AsyncClient(transport=ASGITransport(app=webapp_app), base_url="http://test") as ac:
        response = await ac.get("/api/llm/gpus")
        assert response.status_code == 200
        assert isinstance(response.json()["gpus"], list)
