# High-Value Media Enrichment

PlexMCP provides advanced "Informed Discovery" capabilities by fetching contextual metadata from external high-value sources that are not natively available in Plex Media Server.

## Overview

The enrichment system specifically targets narrative context, historical era data, and cultural trivia. By augmenting standard Plex metadata with these insights, the AI assistant can provide much deeper analysis and thematic recommendations.

### Key Sources
- **Wikipedia**: Primary source for narrative summaries, historical context, and cultural impact.
- **TMDB (deep mode)**: Full cast/crew, keywords, collection membership, production companies.
- **JustWatch**: Best-effort streaming/availability lookup (public JSON endpoint, never blocks the rest of enrichment if unreachable).
- **TVDB / TV Tropes**: Linked metadata for external exploration (search links only, no fetch).

Letterboxd, IMDB, Rotten Tomatoes, Metacritic, and Criterion are deliberately
**not** used — all prohibit scraping in their ToS and run active bot
detection, which isn't worth the exposure at a 50k-item library. See
`docs/plans/DEEP_METADATA_ENRICHMENT.md` for the full rationale.

---

## Standalone Enrichment

You can proactively enrich a specific media item using the **`plex_media_enrichment`** portmanteau tool.

### Quick lookups (title-only, no Plex library link)
- **`enrich_item`**: Fetches a deep summary and contextual description from Wikipedia.
- **`get_external_metadata`**: Generates high-fidelity links to external databases (TMDB, TVDB, TV Tropes).

```python
# Fetch deep Wikipedia context for a movie (no Plex rating_key needed)
plex_media_enrichment(
    operation="enrich_item",
    title="Blade Runner 2049",
    year=2017,
    media_type="movie"
)
```

### Deep dossiers (tied to a Plex library item)
- **`enrich`**: Wikipedia + TMDB deep + JustWatch, LLM-synthesised into a
  structured critical dossier (synopsis, critical overview, "why this
  matters," content warnings, thematic tags, awards, trivia), cached 90 days.
  Also extracts cross-references against every other already-enriched item
  (director, shared cast, TMDB collection, thematic overlap).
- **`bulk_enrich`**: Same, over up to 25 `rating_keys` in one call (the
  webapp's `/enrichment` page runs larger batches as a background job).
- **`get_enrichment`** / **`get_related`**: Read a cached dossier / its
  cross-references without triggering a new fetch.
- **`search_by_theme`** / **`search_by_person`**: Query already-enriched
  items by thematic tag or director.
- **`stale_report`**: List dossiers older than N days (default 90).

```python
# Full dossier for a specific Plex library item, LLM synthesis via ctx.sample
plex_media_enrichment(operation="enrich", rating_key="341017")

# What else in the library shares this item's director?
plex_media_enrichment(operation="get_related", rating_key="341017", relation_type="director")
```

Without an LLM available (no `ctx.sample`, or no provider/model picked in the
webapp), `enrich` still runs — it returns the raw Wikipedia/TMDB/JustWatch
data instead of a synthesised dossier, rather than failing.

Webapp surface: `/media?ratingKey=...` (per-item dossier page) and
`/enrichment` (bulk-run launcher, stale list, theme search) — see
`docs/WEBAPP.md`.

---

## RAG Augmentation (Deep Indexing)

The most powerful application of enrichment is within the **Neural Media RAG** synchronization pipeline.

When syncing your library metadata into the LanceDB vector store, you can enable the `enrich` flag to augment every indexed item with Wikipedia context.

### Enabling Enrichment in RAG
```python
# Sync library metadata with automatic Wikipedia enrichment
plex_rag(operation="sync_metadata", enrich=True)
```

### Why use Enriched RAG?
- **Thematic Search**: Find movies based on era or mood (e.g., *"Find me films set in the Victorian era"* or *"Space operas with social commentary"*).
- **Nuanced Recommendations**: The LLM can "read" the Wikipedia summary stored in the index to explain *why* a movie matches your query.
- **Improved Semantic Accuracy**: Appending narrative summaries to the standard plot improves the embedding's "signal" for complex queries.

---

## Performance and Rate Limiting

The enrichment service implements built-in industrial safeguards:
- **Semaphore-based Concurrency**: Limits concurrent API requests to Wikipedia to avoid rate-limiting or IP bans (default: 5 concurrent requests).
- **Lazy Loading**: Enrichment only triggers if the `enrich` flag is explicitly set or if a manual tool is called.
- **Structured Caching**: Enriched data is stored directly in the LanceDB index to ensure high-speed recall during semantic search without repeatedly hitting external APIs.

---

## Technical Details

- **Quick-lookup service**: `src/plex_mcp/services/enrichment_service.py` (Wikipedia only)
- **Deep enrichment**: `src/plex_mcp/services/enrichment/` (`db.py`, `sources.py`, `synthesis.py`, `crossref.py`, `orchestrator.py`), sqlite-backed at `data/enrichment.db`
- **Tool Logic**: `src/plex_mcp/tools/portmanteau/enrichment.py`
- **Webapp REST**: `webapp/backend/app/api/enrichment.py`, `webapp/backend/app/enrichment_jobs.py` (bulk job state)
- **APIs**: Wikipedia REST API (`/api/rest_v1/page/summary/`), TMDB v3 (`append_to_response=credits,keywords,...`), JustWatch (public JSON, undocumented)

> [!TIP]
> Use `plex_rag(operation="status")` to check if your current index is enriched. An enriched index will typically show a "Deep Context" message in the status output.
