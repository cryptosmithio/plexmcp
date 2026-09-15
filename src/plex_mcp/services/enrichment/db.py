"""SQLite storage for deep media enrichment (reports, person credits, cross-refs)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_db_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_enrichment (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    plex_rating_key      TEXT NOT NULL UNIQUE,
    media_type           TEXT NOT NULL,
    title                TEXT NOT NULL,
    year                 INTEGER,
    enrichment_version   INTEGER NOT NULL DEFAULT 1,
    report_sections      TEXT,
    sources_fetched      TEXT,
    sources_failed       TEXT,
    raw_data             TEXT,
    fetched_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    themes               TEXT,
    director             TEXT,
    tmdb_collection_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_enrichment_rating_key ON media_enrichment(plex_rating_key);
CREATE INDEX IF NOT EXISTS idx_enrichment_updated ON media_enrichment(updated_at);
CREATE INDEX IF NOT EXISTS idx_enrichment_director ON media_enrichment(director);

CREATE TABLE IF NOT EXISTS enrichment_cross_refs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_rating_key    TEXT NOT NULL,
    target_rating_key    TEXT NOT NULL,
    relation_type        TEXT NOT NULL,
    relation_detail      TEXT,
    confidence           REAL DEFAULT 1.0,
    UNIQUE(source_rating_key, target_rating_key, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_crossrefs_source ON enrichment_cross_refs(source_rating_key);
"""


def set_db_path(path: str | Path) -> None:
    """Override the default DB path (used by webapp Tauri packaging)."""
    global _db_path
    with _lock:
        _db_path = Path(path)


def _default_db_path() -> Path:
    # src/plex_mcp/services/enrichment/db.py -> repo_root/data/enrichment.db
    return Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "enrichment.db"


def get_db_path() -> Path:
    return _db_path or _default_db_path()


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    with _lock:
        conn.executescript(SCHEMA)
        conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("report_sections", "sources_fetched", "sources_failed", "raw_data", "themes"):
        if d.get(key):
            with contextlib.suppress(TypeError, ValueError):
                d[key] = json.loads(d[key])
    return d


def save_enrichment(
    rating_key: str,
    *,
    media_type: str,
    title: str,
    year: int | None,
    report_sections: dict[str, Any],
    sources_fetched: list[str],
    sources_failed: list[str],
    raw_data: dict[str, Any],
    themes: list[str],
    director: str | None,
    tmdb_collection_id: int | None,
) -> None:
    conn = get_connection()
    try:
        with _lock, conn:
            conn.execute(
                """
                INSERT INTO media_enrichment
                    (plex_rating_key, media_type, title, year, report_sections,
                     sources_fetched, sources_failed, raw_data, themes, director,
                     tmdb_collection_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(plex_rating_key) DO UPDATE SET
                    media_type=excluded.media_type,
                    title=excluded.title,
                    year=excluded.year,
                    report_sections=excluded.report_sections,
                    sources_fetched=excluded.sources_fetched,
                    sources_failed=excluded.sources_failed,
                    raw_data=excluded.raw_data,
                    themes=excluded.themes,
                    director=excluded.director,
                    tmdb_collection_id=excluded.tmdb_collection_id,
                    enrichment_version=enrichment_version + 1,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    rating_key,
                    media_type,
                    title,
                    year,
                    json.dumps(report_sections, ensure_ascii=False),
                    json.dumps(sources_fetched, ensure_ascii=False),
                    json.dumps(sources_failed, ensure_ascii=False),
                    json.dumps(raw_data, ensure_ascii=False),
                    json.dumps(themes, ensure_ascii=False),
                    director,
                    tmdb_collection_id,
                ),
            )
    finally:
        conn.close()


def load_enrichment(rating_key: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM media_enrichment WHERE plex_rating_key = ?", (rating_key,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def has_fresh_enrichment(rating_key: str, max_age_days: int = 90) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT updated_at FROM media_enrichment WHERE plex_rating_key = ? "
            "AND julianday('now') - julianday(updated_at) < ?",
            (rating_key, max_age_days),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def list_stale(days: int = 90, limit: int = 200) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT plex_rating_key, title, year, updated_at FROM media_enrichment "
            "WHERE julianday('now') - julianday(updated_at) >= ? "
            "ORDER BY updated_at ASC LIMIT ?",
            (days, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_by_theme(theme: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        needle = f'%"{theme.strip().lower()}"%'
        rows = conn.execute(
            "SELECT plex_rating_key, title, year, themes FROM media_enrichment "
            "WHERE lower(themes) LIKE ? ORDER BY title LIMIT ?",
            (needle, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def search_by_director(name: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT plex_rating_key, title, year, director FROM media_enrichment "
            "WHERE lower(director) = lower(?) ORDER BY year LIMIT ?",
            (name.strip(), limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def all_enriched_summaries() -> list[dict[str, Any]]:
    """Lightweight rows for cross-ref matching against the rest of the enriched set."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT plex_rating_key, title, director, themes, tmdb_collection_id, raw_data FROM media_enrichment"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def replace_cross_refs(rating_key: str, refs: list[tuple[str, str, str, float]]) -> None:
    """refs: list of (target_rating_key, relation_type, relation_detail, confidence)."""
    conn = get_connection()
    try:
        with _lock, conn:
            conn.execute("DELETE FROM enrichment_cross_refs WHERE source_rating_key = ?", (rating_key,))
            for target, rel_type, detail, confidence in refs:
                conn.execute(
                    "INSERT OR IGNORE INTO enrichment_cross_refs "
                    "(source_rating_key, target_rating_key, relation_type, relation_detail, confidence) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (rating_key, target, rel_type, detail, confidence),
                )
    finally:
        conn.close()


def get_cross_refs(rating_key: str, relation_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if relation_type:
            rows = conn.execute(
                "SELECT cr.*, me.title AS target_title, me.year AS target_year "
                "FROM enrichment_cross_refs cr LEFT JOIN media_enrichment me "
                "ON me.plex_rating_key = cr.target_rating_key "
                "WHERE cr.source_rating_key = ? AND cr.relation_type = ? "
                "ORDER BY cr.confidence DESC LIMIT ?",
                (rating_key, relation_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT cr.*, me.title AS target_title, me.year AS target_year "
                "FROM enrichment_cross_refs cr LEFT JOIN media_enrichment me "
                "ON me.plex_rating_key = cr.target_rating_key "
                "WHERE cr.source_rating_key = ? "
                "ORDER BY cr.relation_type, cr.confidence DESC LIMIT ?",
                (rating_key, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_enriched() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM media_enrichment").fetchone()[0]
    finally:
        conn.close()
