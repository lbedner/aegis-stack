"""
Tests for cache integration with insights API.
"""

import pytest
from app.core.cache import CacheService


class TestCacheIntegration:
    @pytest.mark.asyncio
    async def test_insights_endpoint_caches(
        self, async_client_with_db: object, auth_headers: dict[str, str]
    ) -> None:
        """Second call to /insights/all returns cached data."""
        from app.core.cache import cache

        await cache.clear()

        resp1 = async_client_with_db.get(  # type: ignore[union-attr]
            "/api/v1/insights/all", headers=auth_headers
        )
        assert resp1.status_code == 200

        # Cache should now have the data, under the build's namespace.
        from app.services.insights.constants import all_insights_key

        cached = await cache.get(all_insights_key())
        assert cached is not None

        resp2 = async_client_with_db.get(  # type: ignore[union-attr]
            "/api/v1/insights/all", headers=auth_headers
        )
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_cache_invalidation(self) -> None:
        """Invalidating cache key removes cached data."""
        c = CacheService()
        await c.set("insights:all", {"test": True})
        assert await c.get("insights:all") is not None

        await c.invalidate("insights:all")
        assert await c.get("insights:all") is None
