# Operational improvements (plan and todo)

**Purpose:** Track **docs, DX, and operations** work that is not product roadmap (see [`ROADMAP.md`](ROADMAP.md) for feature specs).

**Status legend:** `todo` → `in progress` → `done` (date in PR or commit when closing).

---

## Phase 0 — Shipped in repo (bootstrap)

| ID | Item | Status |
|----|------|--------|
| 0.1 | User-facing README + doc hub + `QUICKSTART.md` | done |
| 0.2 | `PLEX.md`, `ARCHITECTURE.md`, `SELF_HOSTING.md` | done |
| 0.3 | Troubleshooting: ordered “diagnose first” flow | done |
| 0.4 | `SELF_HOSTING.md`: Caddy + nginx copy-paste samples | done |
| 0.5 | `RAG.md`: verify `docs_mcp` import (one-liner, Windows + POSIX) | done |
| 0.6 | `plans/README.md`: link to this file | done |

---

## Phase 1 — First-run and support load

| ID | Item | Status |
|----|------|--------|
| 1.1 | `TROUBLESHOOTING.md`: table of symptoms → section | done |
| 1.2 | `docs/assets/`: **SVG** wireframes for Overview, Search, Settings + [WEBAPP.md](../WEBAPP.md) gallery | done |
| 1.3 | **Link checker** in CI — `lychee` job ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)), `continue-on-error: true` while external URLs evolve | done |
| 1.4 | **E2E smoke** (Playwright): `webapp/frontend/e2e/`, `npm run test:e2e`, `just e2e` | done |
| 1.5 | `just version` + README badge policy | done |

---

## Phase 2 — Hardening and scale

| ID | Item | Status |
|----|------|--------|
| 2.1 | **Docker** — [`docker-compose.example.yml`](../../docker-compose.example.yml) + [DOCKER.md](../DOCKER.md) | done |
| 2.2 | `TOOLS.md`: “suggested agent flows” | done |
| 2.3 | Web UI: **BackendStatusBanner** when `/api/health` fails; quieter proxy logging (`NEXT_DEBUG_PROXY=1`) | done |
| 2.4 | **PR template** | done |

---

## Phase 3 — Nice to have

| ID | Item | Status |
|----|------|--------|
| 3.1 | **Video** for `QUICKSTART` — [QUICKSTART.md](../QUICKSTART.md) “Video walkthrough” section (placeholder until a real link exists) | done |
| 3.2 | **i18n** for webapp | cancelled (out of scope until product demand) |
| 3.3 | **Security in CI** — [DEVELOPMENT.md](../DEVELOPMENT.md) documents Semgrep vs optional Bandit/safety | done |

---

## Phase 4 — 2026-09-11 session (settings UX, LLM providers, build pipeline)

Full detail and rationale: [`GAP_ANALYSIS_AND_IMPROVEMENTS.md`](GAP_ANALYSIS_AND_IMPROVEMENTS.md).

| ID | Item | Status |
|----|------|--------|
| 4.1 | Settings → Plex: **Test connection** + **Get a new token** (real PIN sign-in flow) — fresh-install dead end fixed | done |
| 4.2 | Settings → **Diagnostics** panel (Plex/LLM/RAG/*arr checked at once) | done |
| 4.3 | **Local + cloud LLM provider registry** (Ollama/LM Studio/vLLM + OpenAI/Anthropic/DeepSeek/OpenRouter), 0600 per-provider keystore, chat + agentic tool-calling both provider-aware | done |
| 4.4 | Settings → **GPU/VRAM panel**: live telemetry, resident models, Evict all | done |
| 4.5 | Fixed `/health` hardcoded fake `"plex": "connected"` | done |
| 4.6 | Fixed data-bridge bug: `plex_library`/`plex_media`/`plex_search` never carried a `data` field the webapp could read (Movies/Libraries pages silently broken) | done |
| 4.7 | Fixed CORS dropped on the raw `--http` MCP transport (`transport.py`) | done |
| 4.8 | Fixed `fleet-start.config.ps1` pointing the dev launcher at a nonexistent `--serve` flag instead of the real FastAPI backend | done |
| 4.9 | Fixed `just build-native` silently building an unrelated Zed IDE extension instead of the Tauri app (root-level `Cargo.toml`/`build.ps1` collision) — extension moved to `zed-extension/`, its own `--mcp` flag bug fixed too | done |
| 4.10 | Fixed a false-failure in `native/build.ps1`'s post-build step (benign npm stderr warning read as fatal) | done |
| 4.11 | Fixed `scripts/just/cua-nsis-test.ps1`'s `Join-Path` syntax (PS7-only form, fleet invokes via PS5.1) | done |
| 4.12 | Fixed the CUA smoke test's own summary printing "ALL PHASES PASSED" even when phases had failed | done |
| 4.13 | Removed 2 hardcoded real-looking Plex tokens from source (`server_minimal.py`, `webapp/backend/test_plex_pagination.py`) - rotate the real token, both are in git history | done |
| 4.14 | Ruff `ignore` list deduplicated (was ~4x repeated), `S110`/`S112`/`T201` permanently removed | done |
| 4.15 | Deleted confirmed-dead code: root `plex/` package, `server_minimal.py`, `server_fixed_head.py`, stray `.bak` files | done |
| 4.16 | Fixed broken `sandraschi/plex-mcp` GitHub links (real repo is `sandraschi/plexmcp`) fleet-wide in docs | done |
| 4.17 | README Stack section rewritten to match real deps; Help page updated for the new token facility and full page list | done |
| 4.18 | `tests/test_api_plex_auth.py` (7 tests), `tests/test_api_llm_providers.py` (15 tests) added | done |
| 4.19 | **First-run wizard**: 3-step overlay (Plex sign-in → optional LLM provider → done), `localStorage`-gated, silent for an already-working setup | done |

Also flagged (not this repo's fix, tracked as fleet-wide follow-ups): the `mcpb-pack.ps1` path bug and the `--serve`-flag/`module-serve` mismatch both traced back to the canonical `mcp-central-docs` templates and affect ~160 and ~33+ other repos respectively.

---

## How to use this file

- Pick a row, set **in progress** in your branch, then **done** when merged.
- For feature work (RAG quality, new tools), use [`ROADMAP.md`](ROADMAP.md) and the per-project specs in this folder.
- Keep this file **practical** — if an item is obsolete, delete it with a one-line note in the table or `CHANGELOG.md`.

**Last updated:** 2026-09-11
