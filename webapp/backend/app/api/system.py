"""System API endpoints."""

import logging
import os
import secrets

import httpx
from fastapi import APIRouter, Body

from ..config import settings
from ..settings_store import get_current, save_overrides

router = APIRouter()
logger = logging.getLogger(__name__)

PLEX_TV_BASE = "https://plex.tv"
PLEX_PRODUCT = "Plex MCP"


@router.get("/api-docs-info")
async def get_api_docs_info():
    """Return Swagger UI, ReDoc, and OpenAPI schema URLs for this server."""
    base = f"http://localhost:{settings.PORT}"
    return {
        "swagger_ui": f"{base}/docs",
        "redoc": f"{base}/redoc",
        "openapi_json": f"{base}/openapi.json",
        "backend_port": settings.PORT,
        "webapp_url": f"http://localhost:{settings.PORT + 1}/api-docs",
        "note": "Open swagger_ui in a browser to explore and test all plex-mcp REST endpoints.",
    }

    token = os.environ.get("PLEX_TOKEN") or settings.PLEX_TOKEN
    return {
        "status": "healthy",
        "api_version": settings.API_VERSION,
        "plex_configured": bool(token),
    }


@router.get("/settings")
async def get_settings():
    """Current settings (file + env). Tokens masked."""
    current = get_current()
    current["api_version"] = settings.API_VERSION
    return current


@router.patch("/settings")
async def patch_settings(
    body: dict = Body(...),
):
    """Update settings (Plex token, LLM provider/URL/API key). Saved to data/settings.json."""
    allowed = {
        "plex_token",
        "plex_url",
        "llm_provider",
        "llm_base_url",
        "llm_api_key",
        "tmdb_api_key",
        "radarr_url",
        "radarr_api_key",
        "sonarr_url",
        "sonarr_api_key",
        "lidarr_url",
        "lidarr_api_key",
    }
    payload = {k: v for k, v in body.items() if k in allowed and v is not None}
    save_overrides(payload)
    out = get_current()
    out["api_version"] = settings.API_VERSION
    return out


@router.post("/plex/test")
async def test_plex_connection(body: dict = Body(default={})):
    """Validate a Plex URL + token against the real server (dialogic result, never raises)."""
    url = str(body.get("plex_url") or os.environ.get("PLEX_URL") or os.environ.get("PLEX_SERVER_URL") or "").strip()
    token = str(body.get("plex_token") or os.environ.get("PLEX_TOKEN") or "").strip()
    if not url or not token:
        return {"success": False, "message": "Plex URL and token are both required.", "data": None}

    headers = {"Accept": "application/json", "X-Plex-Token": token}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{url.rstrip('/')}/identity", headers=headers)
    except httpx.RequestError as e:
        logger.warning("Plex connection test failed to reach %s: %s", url, e)
        return {"success": False, "message": f"Could not reach {url}: {e}", "data": None}

    if resp.status_code == 401:
        return {
            "success": False,
            "message": "Plex rejected this token (401 Unauthorized). It's invalid or expired - get a new one below.",
            "data": None,
        }
    if resp.status_code != 200:
        return {"success": False, "message": f"Plex server returned HTTP {resp.status_code}.", "data": None}

    try:
        info = resp.json().get("MediaContainer", {})
    except ValueError:
        info = {}
    friendly_name = info.get("friendlyName", "Plex server")
    version = info.get("version", "?")
    return {
        "success": True,
        "message": f"Connected to {friendly_name} (v{version}).",
        "data": {
            "friendly_name": friendly_name,
            "version": version,
            "machine_identifier": info.get("machineIdentifier"),
        },
    }


@router.post("/plex/pin")
async def create_plex_pin():
    """Start the Plex PIN auth flow - returns a code and link the user approves at plex.tv."""
    client_id = secrets.token_hex(16)
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": PLEX_PRODUCT,
        "X-Plex-Client-Identifier": client_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{PLEX_TV_BASE}/api/v2/pins", headers=headers, data={"strong": "true"})
    except httpx.RequestError as e:
        logger.warning("Could not reach plex.tv to create a PIN: %s", e)
        return {"success": False, "message": f"Could not reach plex.tv: {e}", "data": None}

    if resp.status_code != 201:
        return {
            "success": False,
            "message": f"plex.tv rejected the PIN request (HTTP {resp.status_code}).",
            "data": None,
        }

    body = resp.json()
    pin_id = body.get("id")
    code = body.get("code")
    auth_url = (
        f"https://app.plex.tv/auth#?clientID={client_id}&code={code}"
        f"&context%5Bdevice%5D%5Bproduct%5D={PLEX_PRODUCT.replace(' ', '%20')}"
    )
    return {
        "success": True,
        "message": "Open the link and sign in to Plex to authorize this app.",
        "data": {"pin_id": pin_id, "code": code, "client_id": client_id, "auth_url": auth_url},
    }


@router.get("/plex/pin/{pin_id}")
async def poll_plex_pin(pin_id: int, client_id: str):
    """Poll a pending Plex PIN. Once approved in the browser, saves the token to settings."""
    headers = {"Accept": "application/json", "X-Plex-Client-Identifier": client_id}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{PLEX_TV_BASE}/api/v2/pins/{pin_id}", headers=headers)
    except httpx.RequestError as e:
        logger.warning("Could not poll plex.tv PIN %s: %s", pin_id, e)
        return {"success": False, "message": f"Could not reach plex.tv: {e}", "data": None}

    if resp.status_code != 200:
        return {"success": False, "message": f"Could not check PIN status (HTTP {resp.status_code}).", "data": None}

    token = resp.json().get("authToken")
    if not token:
        return {
            "success": True,
            "message": "Waiting for authorization in the browser...",
            "data": {"authorized": False},
        }

    save_overrides({"plex_token": token})
    return {
        "success": True,
        "message": "Plex token obtained and saved.",
        "data": {"authorized": True, "token_set": True},
    }


@router.get("/diagnostics")
async def get_diagnostics():
    """Run every connectivity/config check at once: one traffic-light list
    instead of hunting through Plex/Chat/Search/*arr pages one at a time to
    find out which one is actually broken.
    """
    from ..mcp.client import mcp_client
    from .llm import list_models

    checks: list[dict] = []

    try:
        plex_result = await test_plex_connection({})
        checks.append(
            {
                "id": "plex",
                "label": "Plex Media Server",
                "status": "ok" if plex_result.get("success") else "error",
                "message": plex_result.get("message", ""),
            }
        )
    except Exception as e:
        checks.append({"id": "plex", "label": "Plex Media Server", "status": "error", "message": str(e)})

    try:
        llm_result = await list_models()
        models = llm_result.get("models") or []
        if models:
            provider = llm_result.get("provider", "configured provider")
            checks.append(
                {
                    "id": "llm",
                    "label": "LLM provider",
                    "status": "ok",
                    "message": f"{len(models)} model(s) available via {provider}.",
                }
            )
        else:
            checks.append(
                {
                    "id": "llm",
                    "label": "LLM provider",
                    "status": "warn",
                    "message": llm_result.get("error") or "No models found. Check Settings → LLM.",
                }
            )
    except Exception as e:
        checks.append({"id": "llm", "label": "LLM provider", "status": "error", "message": str(e)})

    try:
        rag_result = await mcp_client.call_tool("plex_rag", {"operation": "status"})
        data = rag_result.get("data") if isinstance(rag_result.get("data"), dict) else {}
        available = bool(data.get("available")) if data else bool(rag_result.get("success"))
        count = data.get("count") if data else None
        if available and count:
            checks.append(
                {
                    "id": "rag",
                    "label": "Semantic search (RAG)",
                    "status": "ok",
                    "message": f"Index built, {count} item(s).",
                }
            )
        elif available:
            checks.append(
                {
                    "id": "rag",
                    "label": "Semantic search (RAG)",
                    "status": "warn",
                    "message": "RAG backend is available but the index looks empty - run Reindex in Settings.",
                }
            )
        else:
            checks.append(
                {
                    "id": "rag",
                    "label": "Semantic search (RAG)",
                    "status": "warn",
                    "message": "RAG not built yet - run Reindex in Settings to enable semantic search.",
                }
            )
    except Exception as e:
        checks.append(
            {
                "id": "rag",
                "label": "Semantic search (RAG)",
                "status": "warn",
                "message": f"Could not check RAG status ({e}).",
            }
        )

    try:
        from plex_mcp.services.arr_client import get_arr_stack_status

        arr_result = await get_arr_stack_status()
        if not arr_result.get("any_configured"):
            checks.append(
                {
                    "id": "arr",
                    "label": "*arr stack (Radarr/Sonarr/Lidarr)",
                    "status": "info",
                    "message": "Not configured (optional) - set up in Settings if you use Radarr/Sonarr/Lidarr.",
                }
            )
        else:
            unreachable = [
                name
                for name in ("radarr", "sonarr", "lidarr")
                if arr_result.get(name, {}).get("configured") and not arr_result.get(name, {}).get("reachable")
            ]
            if unreachable:
                checks.append(
                    {
                        "id": "arr",
                        "label": "*arr stack (Radarr/Sonarr/Lidarr)",
                        "status": "warn",
                        "message": f"Configured but unreachable: {', '.join(unreachable)}.",
                    }
                )
            else:
                checks.append(
                    {
                        "id": "arr",
                        "label": "*arr stack (Radarr/Sonarr/Lidarr)",
                        "status": "ok",
                        "message": "All configured *arr apps are reachable.",
                    }
                )
    except Exception as e:
        checks.append(
            {
                "id": "arr",
                "label": "*arr stack (Radarr/Sonarr/Lidarr)",
                "status": "warn",
                "message": f"Could not check *arr status ({e}).",
            }
        )

    overall = "ok"
    if any(c["status"] == "error" for c in checks):
        overall = "error"
    elif any(c["status"] == "warn" for c in checks):
        overall = "warn"

    return {"success": True, "overall": overall, "checks": checks}
