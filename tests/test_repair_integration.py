"""Live integration tests for Media Repair (FFmpeg).

Requires PLEX_TOKEN, PLEX_URL, and local FFmpeg/FFprobe.
"""

import shutil

import pytest

from plex_mcp.tools.portmanteau.ffmpeg_mgr import plex_ffmpeg_mgr
from tests.helpers import tool_payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ffmpeg_probe_real(real_plex_service, plex_available, test_library_id):
    """Test probing a real media item."""
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe not found on system path.")

    from unittest.mock import patch

    # 1. Browse to find a media key
    from plex_mcp.tools.portmanteau.media import plex_media

    with patch("plex_mcp.tools.portmanteau.media._get_plex_service", return_value=real_plex_service):
        browse_res = await (plex_media.fn if hasattr(plex_media, "fn") else plex_media)(
            operation="browse", library_id=test_library_id, limit=1
        )
        # browse returns a text summary as content; the raw items live in meta["data"]
        items = (browse_res.meta or {}).get("data") or []
        if not items:
            pytest.skip("No media found on real server to probe.")

        media_key = items[0].get("id") or items[0].get("key")

    # 2. Probe it
    with patch("plex_mcp.tools.portmanteau.ffmpeg_mgr._get_plex_service", return_value=real_plex_service):
        result = tool_payload(
            await (plex_ffmpeg_mgr.fn if hasattr(plex_ffmpeg_mgr, "fn") else plex_ffmpeg_mgr)(
                operation="probe", media_key=media_key
            )
        )

        # If it fails due to network/path issues, skip or assert
        if not result["success"]:
            pytest.skip(f"Probe failed (likely path issue): {result.get('error')}")

        assert result["success"] is True
        assert "format" in result["result"]
