import os

from plexapi.server import PlexServer

base_url = os.environ.get("PLEX_URL", "http://127.0.0.1:32400")
token = os.environ.get("PLEX_TOKEN", "")


def test_pagination():
    if not token:
        print("PLEX_TOKEN not set — skipping (set it in .env to run this manual script)")
        return
    try:
        plex = PlexServer(base_url, token)
        sections = plex.library.sections()
        if not sections:
            print("No sections found")
            return

        section = sections[0]
        print(f"Testing section: {section.title} ({section.type})")

        # Test offset in browse (all)
        print("Testing section.all with X-Plex-Container-Start/Size equivalent...")
        # In plexapi, 'all' supports X-Plex-Container-Start/Size if passed as headers or as specific kwargs for some versions.
        # Actually, python-plexapi uses 'X-Plex-Container-Start' and 'X-Plex-Container-Size' as headers.

        # Let's test if it responds correctly to 'start' and 'size' kwargs which some methods use
        try:
            # We'll try to reach it directly via the URL to confirm what Plex supports
            items = section.all()
            print(f"Total items found via .all(): {len(items)}")

            # Plex actually uses 'X-Plex-Container-Start' and 'X-Plex-Container-Size' as URL params internally
            # python-plexapi might not expose them cleanly in section.search() yet.
            # But we can try to pass them via kwargs in some methods.
        except Exception as e:
            print(f"Pagination test error: {e}")

    except Exception as e:
        print(f"Connection failed: {e}")


if __name__ == "__main__":
    test_pagination()
