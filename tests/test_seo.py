"""
Phase 7: SEO & Web Intelligence integration tests.

All tests require live API keys and are skipped when credentials are absent.
"""

import os

import pytest

requires_dataforseo = pytest.mark.skipif(
    not os.environ.get("DATAFORSEO_API_LOGIN")
    or not os.environ.get("DATAFORSEO_API_PASSWORD"),
    reason="DATAFORSEO_API_LOGIN / DATAFORSEO_API_PASSWORD not set",
)

requires_brave = pytest.mark.skipif(
    not os.environ.get("BRAVE_API_KEY"),
    reason="BRAVE_API_KEY not set",
)


@requires_dataforseo
class TestDataForSEO:
    def test_dataforseo_keyword_volume(self):
        """Search volume for a known German political keyword should be > 0."""
        from spdbe.external.dataforseo import get_keyword_data

        result = get_keyword_data("Mietpreisbremse Berlin")
        assert "search_volume" in result
        assert result["search_volume"] > 0, f"Expected search_volume > 0, got {result}"

    def test_dataforseo_related_keywords(self):
        """Related keywords should return a non-empty list."""
        from spdbe.external.dataforseo import get_related_keywords

        results = get_related_keywords("Mietpreisbremse Berlin", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0, "Expected at least one related keyword"
        assert "keyword" in results[0]


@requires_brave
class TestBraveSearch:
    def test_brave_search_returns_results(self):
        """Brave Search should return web results for a political query."""
        from spdbe.external.brave import brave_search

        results = brave_search("SPD Berlin Mietenpolitik")
        assert isinstance(results, list)
        assert len(results) > 0, "Expected at least one search result"
        first = results[0]
        assert "title" in first
        assert "url" in first
        assert "description" in first
