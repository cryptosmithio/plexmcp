"""Unified local + cloud LLM provider registry, keystore, chat proxy, and
Ollama VRAM management.

Vendored from the fleet template (mcp-central-docs/templates/llm/), pilot
proven in arxiv-mcp. Two problems solved together, on purpose: a GPU-less
machine can still use plex-mcp's AI features via a cloud provider, and a
machine with a shared/full GPU can evict other resident models instead of
an AI task just failing with an opaque timeout.

The webapp never talks to a provider from the browser — all traffic goes
through these functions on the backend. Cloud API keys live in a 0600
keystore file next to settings.json (or env vars, which win), never in
settings.json itself and never echoed back in a GET response.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from .settings_store import _app_data_dir

logger = logging.getLogger(__name__)

LOCAL_PROBE_TIMEOUT = 3.0
CLOUD_TIMEOUT = 30.0
CHAT_TIMEOUT = 120.0
KEYSTORE_NAME = "llm_keys.json"
ANTHROPIC_VERSION = "2023-06-01"
# Ollama's /v1 endpoint ignores options (e.g. num_ctx); native /api/chat honors
# it. Long-context models default to a huge KV cache that offloads to CPU
# (measured elsewhere in the fleet: 3 tok/s vs 79 tok/s) unless capped here.
OLLAMA_NUM_CTX = 32768
DEFAULT_KEEP_ALIVE = "10m"

PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "ollama",
        "label": "Ollama",
        "kind": "local",
        "base_url": "http://127.0.0.1:11434",
        "chat_path": "/api/chat",
        "models_path": "/api/tags",
        "tag_style": "ollama",
        "key_env": None,
        "curated": [],
    },
    {
        "id": "lmstudio",
        "label": "LM Studio",
        "kind": "local",
        "base_url": "http://127.0.0.1:1234",
        "chat_path": "/v1/chat/completions",
        "models_path": "/v1/models",
        "tag_style": "openai",
        "key_env": None,
        "curated": [],
    },
    {
        "id": "vllm",
        "label": "vLLM",
        "kind": "local",
        "base_url": "http://127.0.0.1:8000",
        "chat_path": "/v1/chat/completions",
        "models_path": "/v1/models",
        "tag_style": "openai",
        "key_env": None,
        "curated": [],
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "kind": "cloud",
        "base_url": "https://api.openai.com/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "tag_style": "openai",
        "key_env": "OPENAI_API_KEY",
        "curated": ["gpt-4o", "gpt-4o-mini"],
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "kind": "cloud",
        "base_url": "https://api.anthropic.com",
        "chat_path": "/v1/messages",
        "models_path": "/v1/models",
        "tag_style": "anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "curated": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "kind": "cloud",
        "base_url": "https://api.deepseek.com",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "tag_style": "openai",
        "key_env": "DEEPSEEK_API_KEY",
        "curated": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "kind": "cloud",
        "base_url": "https://openrouter.ai/api/v1",
        "chat_path": "/chat/completions",
        "models_path": "/models",
        "tag_style": "openai",
        "key_env": "OPENROUTER_API_KEY",
        "curated": ["openrouter/auto", "anthropic/claude-sonnet-4.5", "openai/gpt-4o"],
    },
)


def get_provider(provider_id: str) -> dict[str, Any] | None:
    """Return the registry row for a provider ID, or None."""
    for row in PROVIDERS:
        if row["id"] == provider_id:
            return row
    return None


def require_provider(provider_id: str) -> dict[str, Any]:
    row = get_provider(provider_id)
    if row is None:
        known = ", ".join(r["id"] for r in PROVIDERS)
        raise ValueError(f"Unknown provider '{provider_id}'. Known: {known}")
    return row


def keystore_path() -> Path:
    if os.environ.get("PLEX_TAURI") == "1":
        base = _app_data_dir()
    else:
        base = Path(__file__).resolve().parent.parent / "data"
    return base / KEYSTORE_NAME


def _read_keystore() -> dict[str, str]:
    path = keystore_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("llm keystore unreadable (%s); treating as empty", exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and v}


def _write_keystore(entries: dict[str, str]) -> None:
    path = keystore_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        logger.debug("chmod 0600 on keystore failed (non-POSIX fs); continuing")
    tmp.replace(path)
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def get_key(provider_id: str) -> str:
    """Resolve an API key: env var first, then keystore. Empty when unset."""
    row = require_provider(provider_id)
    env_name = row.get("key_env")
    if env_name:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    stored = _read_keystore().get(provider_id, "")
    if stored:
        return stored
    # Pre-registry installs stored one flat "openai" key in settings.json
    # (settings_store.py's llm_api_key) rather than this keystore - honor it
    # for "openai" specifically so an existing setup isn't silently orphaned.
    if provider_id == "openai":
        legacy = os.environ.get("LLM_API_KEY", "").strip()
        if legacy:
            return legacy
    return ""


def is_configured(provider_id: str) -> bool:
    """True when a cloud provider has a key available. Locals need no key."""
    row = require_provider(provider_id)
    if row["kind"] == "local":
        return True
    return bool(get_key(provider_id))


def save_key(provider_id: str, api_key: str) -> None:
    row = require_provider(provider_id)
    if row["kind"] != "cloud":
        raise ValueError(f"Provider '{provider_id}' takes no API key")
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Empty API key")
    entries = _read_keystore()
    entries[provider_id] = key
    _write_keystore(entries)


def delete_key(provider_id: str) -> bool:
    require_provider(provider_id)
    entries = _read_keystore()
    if provider_id not in entries:
        return False
    del entries[provider_id]
    _write_keystore(entries)
    return True


def public_provider_info() -> list[dict[str, Any]]:
    """Registry rows safe for GET responses: capability flags, never key bytes."""
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "kind": r["kind"],
            "base_url": r["base_url"],
            "needs_key": r["kind"] == "cloud",
            "key_env": r.get("key_env"),
            "configured": is_configured(r["id"]),
        }
        for r in PROVIDERS
    ]


def _parse_model_list(tag_style: str, payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if tag_style == "ollama":
        models = payload.get("models") or []
        return [m.get("name", "") for m in models if isinstance(m, dict) and m.get("name")]
    data = payload.get("data") or []
    return [m.get("id", "") for m in data if isinstance(m, dict) and m.get("id")]


async def probe_local(provider_id: str) -> tuple[bool, list[str]]:
    """Probe a local engine (fast timeout). Returns (reachable, models)."""
    row = require_provider(provider_id)
    if row["kind"] != "local":
        raise ValueError(f"Provider '{provider_id}' is not local")
    url = row["base_url"] + row["models_path"]
    try:
        async with httpx.AsyncClient(timeout=LOCAL_PROBE_TIMEOUT) as client:
            resp = await client.get(url)
    except Exception as exc:
        logger.debug("local probe %s failed: %s", provider_id, exc)
        return False, []
    if resp.status_code >= 500:
        return False, []
    try:
        models = _parse_model_list(row["tag_style"], resp.json())
    except Exception:
        models = []
    return True, models


async def list_provider_models(provider_id: str) -> dict[str, Any]:
    """Model list with source flag. Cloud: live when keyed, else curated."""
    row = require_provider(provider_id)
    if row["kind"] == "local":
        reachable, models = await probe_local(provider_id)
        return {"provider": provider_id, "models": models, "source": "live" if reachable else "none"}
    key = get_key(provider_id)
    if not key:
        return {"provider": provider_id, "models": list(row["curated"]), "source": "curated"}
    url = row["base_url"] + row["models_path"]
    headers = _auth_headers(row, key)
    try:
        async with httpx.AsyncClient(timeout=CLOUD_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            models = _parse_model_list(row["tag_style"], resp.json())
    except Exception as exc:
        logger.warning("live model list for %s failed (%s); curated fallback", provider_id, exc)
        return {"provider": provider_id, "models": list(row["curated"]), "source": "curated"}
    if not models:
        return {"provider": provider_id, "models": list(row["curated"]), "source": "curated"}
    return {"provider": provider_id, "models": models, "source": "live"}


def _auth_headers(row: dict[str, Any], api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if row["id"] == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif row["id"] == "openrouter":
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "http://127.0.0.1:10741/"
        headers["X-Title"] = "Plex MCP"
    elif row["kind"] == "cloud":
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _openai_body(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"model": model, "messages": messages, "stream": False}


def _to_anthropic(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Map an OpenAI-style messages array to the Anthropic Messages API body."""
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(str(content))
        elif role in ("user", "assistant"):
            converted.append({"role": role, "content": str(content)})
        else:
            converted.append({"role": "user", "content": str(content)})
    body: dict[str, Any] = {"model": model, "max_tokens": 4096, "messages": converted}
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    return body


def _from_anthropic(payload: dict[str, Any]) -> str:
    blocks = payload.get("content") or []
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    return "".join(texts)


def _to_ollama_native(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    converted = [{"role": m.get("role", "user"), "content": str(m.get("content", ""))} for m in messages]
    return {
        "model": model,
        "messages": converted,
        "stream": False,
        "options": {"num_ctx": OLLAMA_NUM_CTX},
    }


def _from_ollama_native(payload: dict[str, Any]) -> str:
    return str((payload.get("message") or {}).get("content", ""))


def _ollama_stream_text(payload: dict[str, Any]) -> str:
    if payload.get("done"):
        return ""
    return str((payload.get("message") or {}).get("content", ""))


async def chat_complete(provider_id: str, model: str, messages: list[dict[str, Any]]) -> str:
    """Non-streaming chat via the backend proxy. Returns assistant text.

    Never called from the browser directly - the webapp always goes through
    this so cloud keys stay server-side.
    """
    row = require_provider(provider_id)
    if not model.strip():
        raise ValueError("Empty model name")
    key = get_key(provider_id) if row["kind"] == "cloud" else ""
    if row["kind"] == "cloud" and not key:
        raise ValueError(f"Provider '{provider_id}' has no API key configured")
    headers = _auth_headers(row, key)
    if row["id"] == "anthropic":
        url = row["base_url"] + row["chat_path"]
        body = _to_anthropic(model, messages)
    elif row["id"] == "ollama":
        url = row["base_url"] + row["chat_path"]
        body = _to_ollama_native(model, messages)
    else:
        url = row["base_url"] + row["chat_path"]
        body = _openai_body(model, messages)
    try:
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        raise RuntimeError(f"Provider '{provider_id}' HTTP {status}") from exc
    except Exception as exc:
        raise RuntimeError(f"Provider '{provider_id}' unreachable ({exc})") from exc
    if row["id"] == "anthropic":
        return _from_anthropic(data)
    if row["id"] == "ollama":
        return _from_ollama_native(data)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Provider '{provider_id}' returned an unexpected body") from exc


def _openai_sse_chunk(model: str, text: str) -> bytes:
    import time
    import uuid

    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return ("data: " + json.dumps(chunk) + "\n\n").encode("utf-8")


async def chat_stream(
    provider_id: str,
    model: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[bytes]:
    """Streaming chat as OpenAI-style SSE bytes, normalized across providers."""
    row = require_provider(provider_id)
    if not model.strip():
        raise ValueError("Empty model name")
    key = get_key(provider_id) if row["kind"] == "cloud" else ""
    if row["kind"] == "cloud" and not key:
        raise ValueError(f"Provider '{provider_id}' has no API key configured")
    headers = _auth_headers(row, key)
    headers["Accept"] = "text/event-stream"
    if row["id"] == "anthropic":
        url = row["base_url"] + row["chat_path"]
        body = _to_anthropic(model, messages)
        body["stream"] = True
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client, client.stream(
            "POST", url, json=body, headers=headers
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload in ("[DONE]", ""):
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "content_block_delta":
                    text = (event.get("delta") or {}).get("text", "")
                    if text:
                        yield _openai_sse_chunk(model, text)
    elif row["id"] == "ollama":
        url = row["base_url"] + row["chat_path"]
        body = _to_ollama_native(model, messages)
        body["stream"] = True
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client, client.stream(
            "POST", url, json=body, headers=headers
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                text = line.strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    continue
                delta = _ollama_stream_text(event)
                if delta:
                    yield _openai_sse_chunk(model, delta)
    else:
        url = row["base_url"] + row["chat_path"]
        body = _openai_body(model, messages)
        body["stream"] = True
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client, client.stream(
            "POST", url, json=body, headers=headers
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield (line + "\n\n").encode("utf-8")
    yield b"data: [DONE]\n\n"


# --- VRAM management (Ollama only - the local engine that actually loads
# weights into VRAM this fleet cares about) --------------------------------


def _parse_nvidia_smi(stdout: str) -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": ",".join(parts[1:-3]).strip(),
                    "total_mb": int(parts[-3]),
                    "used_mb": int(parts[-2]),
                    "free_mb": int(parts[-1]),
                }
            )
        except ValueError:
            continue
    return gpus


def gpu_vram() -> list[dict[str, Any]]:
    """Live per-GPU VRAM via nvidia-smi. Empty list when unavailable (no GPU,
    no driver, timeout) - that's the normal, expected case on a GPU-less
    machine, not an error."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.debug("nvidia-smi unavailable (%s)", exc)
        return []
    if proc.returncode != 0:
        return []
    return _parse_nvidia_smi(proc.stdout)


def _same_model(a: str, b: str) -> bool:
    """Loose tag equality: an untagged name matches any tag of the same repo."""
    if a == b:
        return True
    a_repo, _, a_tag = a.partition(":")
    b_repo, _, b_tag = b.partition(":")
    if a_repo != b_repo:
        return False
    return not a_tag or not b_tag or a_tag == b_tag


async def ollama_loaded(base_url: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    """Residents on the Ollama engine (`/api/ps`): name + VRAM + expiry."""
    result: dict[str, Any] = {"engine": False, "models": []}
    base = (base_url or "").rstrip("/") or "http://127.0.0.1:11434"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            ps = await client.get(base + "/api/ps")
            if ps.status_code != 200:
                return result
            result["engine"] = True
            try:
                items = ps.json().get("models") or []
            except Exception:
                items = []
            for m in items:
                if not isinstance(m, dict) or not m.get("name"):
                    continue
                result["models"].append(
                    {
                        "name": m["name"],
                        "size_vram_mb": round((m.get("size_vram") or 0) / 1048576),
                        "expires_at": m.get("expires_at") or "",
                    }
                )
    except Exception as exc:
        logger.debug("ollama loaded probe failed (%s)", exc)
    return result


async def switch_ollama_model(keep: str, base_url: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    """Make `keep` the only loaded Ollama model: evict the rest, warm `keep`.

    This is the piece that keeps an AI task from failing outright when VRAM
    is already full of some other model - evict what's resident, then load
    the one actually needed. Empty `keep` evicts everything (full release,
    e.g. before handing the GPU to something else). All failures are
    non-fatal; the caller reports what happened.
    """
    result: dict[str, Any] = {"evicted": [], "warmed": False, "engine": False}
    keep = (keep or "").strip()
    base = (base_url or "").rstrip("/") or "http://127.0.0.1:11434"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            ps = await client.get(base + "/api/ps")
            if ps.status_code != 200:
                return result
            result["engine"] = True
            try:
                loaded = [
                    m.get("name", "") for m in (ps.json().get("models") or []) if isinstance(m, dict) and m.get("name")
                ]
            except Exception:
                loaded = []
            if keep and any(_same_model(keep, name) for name in loaded):
                result["warmed"] = True
            for name in loaded:
                if keep and _same_model(keep, name):
                    continue
                try:
                    await client.post(base + "/api/generate", json={"model": name, "keep_alive": 0})
                    result["evicted"].append(name)
                except Exception as exc:
                    logger.warning("ollama evict %s failed (%s)", name, exc)
            if keep and not result["warmed"]:
                try:
                    async with httpx.AsyncClient(timeout=180.0) as warm_client:
                        warm = await warm_client.post(
                            base + "/api/generate",
                            json={
                                "model": keep,
                                "prompt": " ",
                                "keep_alive": DEFAULT_KEEP_ALIVE,
                                "options": {"num_predict": 1},
                            },
                        )
                        result["warmed"] = warm.status_code == 200
                except Exception as exc:
                    logger.warning("ollama warm %s failed (%s)", keep, exc)
    except Exception as exc:
        logger.warning("ollama switch failed (%s)", exc)
    return result


def onboarding_state() -> dict[str, Any]:
    """Fresh-install starter facts: what exists, what can be installed, best path."""
    clouds = {r["id"]: is_configured(r["id"]) for r in PROVIDERS if r["kind"] == "cloud"}
    return {
        "locals": [
            {"id": r["id"], "label": r["label"], "port": _port_hint(r["base_url"])}
            for r in PROVIDERS
            if r["kind"] == "local"
        ],
        "clouds_configured": [pid for pid, ok in clouds.items() if ok],
        "recommendation": _recommend_path(clouds),
    }


def _port_hint(base_url: str) -> int | None:
    try:
        return int(base_url.rsplit(":", 1)[1].split("/")[0])
    except (ValueError, IndexError):
        return None


def _recommend_path(clouds: dict[str, bool]) -> dict[str, str]:
    if any(clouds.values()):
        first = next(pid for pid, ok in clouds.items() if ok)
        return {
            "path": f"cloud:{first}",
            "reason": f"{first} key already configured - chat works immediately.",
        }
    return {
        "path": "local:ollama",
        "reason": "No cloud key configured yet. Install Ollama for a free local model, "
        "or paste a cloud API key in Settings if you don't have a capable GPU.",
    }
