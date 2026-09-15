"""Unit tests for PlexService.search_media media_type filtering.

Regression coverage for a bug where `media_type` was accepted by the API/tool
layer but silently dropped (never reached PlexServer.search's `mediatype`
param), so search results mixed movies/shows/episodes/photos/etc. despite the
filter (see webapp/backend/app/api/search.py -> plex_search -> PlexService).
"""

from __future__ import annotations

from unittest.mock import MagicMock, create_autospec

import pytest
from plexapi.library import Library
from plexapi.server import PlexServer

from plex_mcp.services.plex_service import PlexService


class _FakeItem:
    def __init__(self, rating_key: str, title: str, item_type: str):
        self.ratingKey = rating_key
        self.title = title
        self.type = item_type
        self.year = None
        self.thumb = ""
        self.summary = ""


def _make_service_with_autospec_server() -> tuple[PlexService, PlexServer]:
    """PlexService wired to an autospec'd PlexServer so unexpected kwargs raise TypeError,
    mirroring the real bug (media_type leaking into a call that doesn't accept it)."""
    svc = PlexService(base_url="http://example.invalid", token="token")
    svc._initialized = True
    fake_server = create_autospec(PlexServer, instance=True)
    # PlexServer.library is autospecced as a bare NonCallableMagicMock with no
    # attributes (Library is a runtime-assigned instance attribute, not part of
    # the class spec); replace it with its own autospec so `.search` exists.
    fake_server.library = create_autospec(Library, instance=True)
    svc.server = fake_server
    return svc, fake_server


class TestSearchMediaTypeFiltering:
    def test_media_type_maps_to_mediatype_on_server_search(self):
        """media_type must reach PlexServer.search as `mediatype`, not leak as a stray kwarg."""
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.search.return_value = [_FakeItem("1", "A Show", "show")]

        results = svc._search_media_sync("anime", 10, None, 0, media_type="show")

        fake_server.search.assert_called_once()
        _, kwargs = fake_server.search.call_args
        assert kwargs.get("mediatype") == "show"
        assert "media_type" not in kwargs
        assert results == [{"id": "1", "title": "A Show", "type": "show", "year": None, "thumb": "", "summary": ""}]

    def test_media_type_does_not_raise_type_error(self):
        """Autospec'd PlexServer.search has no **kwargs; a leaked media_type would TypeError."""
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.search.return_value = []

        # Should not raise TypeError: search() got an unexpected keyword argument 'media_type'
        svc._search_media_sync("anime", 10, None, 0, media_type="movie")

    def test_explicit_libtype_wins_over_media_type_alias(self):
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.search.return_value = []

        svc._search_media_sync("anime", 10, None, 0, libtype="movie", media_type="show")

        _, kwargs = fake_server.search.call_args
        assert kwargs.get("mediatype") == "movie"

    @pytest.mark.asyncio
    async def test_search_media_forwards_media_type(self):
        """Public async search_media() forwards media_type through to the sync helper."""
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.search.return_value = [_FakeItem("2", "A Movie", "movie")]

        results = await svc.search_media(query="anime", limit=10, media_type="movie")

        assert len(results) == 1
        assert results[0].type == "movie"
        _, kwargs = fake_server.search.call_args
        assert kwargs.get("mediatype") == "movie"

    def test_media_type_on_section_search_does_not_leak(self):
        """library_id branch: media_type must become `libtype` for Section.search, not a stray kwarg."""
        svc = PlexService(base_url="http://example.invalid", token="token")
        svc._initialized = True

        fake_section = MagicMock()
        fake_section.search.return_value = [_FakeItem("3", "A Show", "show")]

        fake_server = MagicMock()
        fake_server.library.sectionByID.return_value = fake_section
        svc.server = fake_server

        svc._search_media_sync("anime", 10, "1", 0, media_type="show")

        _, kwargs = fake_section.search.call_args
        assert kwargs.get("libtype") == "show"
        assert "media_type" not in kwargs


class TestAdvancedSearchWithoutLibraryId:
    """Regression coverage for a bug where any advanced filter (title, genre,
    actor, year, ...) forwarded to `_search_media_sync` without a library_id
    raised `TypeError: PlexServer.search() got an unexpected keyword argument`,
    because PlexServer.search()'s Hub search has a fixed signature with no
    **kwargs support. Library.search() (server.library.search) searches across
    every section and does accept arbitrary filter kwargs, so advanced filters
    must route there instead when no library_id is given.
    """

    def test_title_filter_without_library_id_does_not_raise(self):
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.library.search.return_value = [_FakeItem("1", "Anime Movie", "movie")]

        # Should not raise TypeError: search() got an unexpected keyword argument 'title'
        results = svc._search_media_sync("anime", 20, None, 0, title="anime")

        fake_server.library.search.assert_called_once()
        _, kwargs = fake_server.library.search.call_args
        assert kwargs.get("title") == "anime"
        assert results == [
            {"id": "1", "title": "Anime Movie", "type": "movie", "year": None, "thumb": "", "summary": ""}
        ]

    def test_genre_filter_without_library_id_does_not_raise(self):
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.library.search.return_value = []

        svc._search_media_sync("anime", 20, None, 0, genre=["Action"])

        fake_server.search.assert_not_called()
        _, kwargs = fake_server.library.search.call_args
        assert kwargs.get("genre") == ["Action"]
        # No explicit title filter given, so `query` is used as the title search term.
        assert kwargs.get("title") == "anime"

    def test_explicit_title_wins_over_query_for_library_search(self):
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.library.search.return_value = []

        svc._search_media_sync("anime", 20, None, 0, title="Cowboy Bebop", actor="Koichi Yamadera")

        _, kwargs = fake_server.library.search.call_args
        assert kwargs.get("title") == "Cowboy Bebop"
        assert kwargs.get("actor") == "Koichi Yamadera"

    def test_media_type_maps_to_libtype_for_library_search(self):
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.library.search.return_value = []

        svc._search_media_sync("anime", 20, None, 0, media_type="show", genre="Comedy")

        _, kwargs = fake_server.library.search.call_args
        assert kwargs.get("libtype") == "show"
        assert "media_type" not in kwargs

    def test_plain_query_with_no_filters_still_uses_hub_search(self):
        """No advanced filters present: PlexServer.search() (Hub search) is unaffected."""
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.search.return_value = [_FakeItem("2", "A Movie", "movie")]

        results = svc._search_media_sync("anime", 20, None, 0)

        fake_server.search.assert_called_once()
        fake_server.library.search.assert_not_called()
        assert results[0]["title"] == "A Movie"

    @pytest.mark.asyncio
    async def test_advanced_search_media_forwards_advanced_filters(self):
        """Public async search_media() forwards advanced filters without library_id."""
        svc, fake_server = _make_service_with_autospec_server()
        fake_server.library.search.return_value = [_FakeItem("4", "A Show", "show")]

        results = await svc.search_media(query="anime", limit=20, title="anime")

        assert len(results) == 1
        fake_server.library.search.assert_called_once()
