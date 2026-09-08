"""
Tests for RedditCollector -- Reddit post tracking.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.insights.adapters.collectors.reddit import RedditCollector
from app.services.insights.constants import MetricKeys, SourceKeys
from app.services.insights.models import (
    InsightEvent,
    InsightMetric,
    InsightMetricType,
    InsightSource,
)
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ._collector_fixtures import collector_kwargs, seed_project_for_collector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_reddit(
    session: AsyncSession,
) -> tuple[InsightSource, dict[str, InsightMetricType]]:
    """Seed reddit source with metric types."""
    source = InsightSource(
        key=SourceKeys.REDDIT,
        display_name="Reddit",
        collection_interval_hours=None,  # On-demand only
        enabled=True,
    )
    session.add(source)
    await session.flush()

    metric_types: dict[str, InsightMetricType] = {}
    mt = InsightMetricType(
        source_id=source.id,  # type: ignore[arg-type]
        key=MetricKeys.POST_STATS,
        display_name="Post Stats",
        unit="json",
    )
    session.add(mt)
    await session.flush()
    metric_types[MetricKeys.POST_STATS] = mt

    return source, metric_types


# ---------------------------------------------------------------------------
# Tests: RedditCollector
# ---------------------------------------------------------------------------


class TestRedditCollectorAddPost:
    """Test add_post() method."""

    @pytest.mark.asyncio
    async def test_add_post_success(self, async_db_session: AsyncSession) -> None:
        """Happy path: add a Reddit post with stats."""
        await _seed_reddit(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs):
            """Mock Reddit JSON API response."""
            # Reddit returns array of listings
            return MagicMock(
                json=lambda: [
                    {
                        "data": {
                            "children": [
                                {
                                    "data": {
                                        "id": "abc123",
                                        "subreddit": "Python",
                                        "title": "Announcing Aegis Stack",
                                        "ups": 150,
                                        "num_comments": 25,
                                        "view_count": 5000,
                                        "upvote_ratio": 0.95,
                                        "created_utc": 1712900000,
                                        "url": "https://reddit.com/r/Python/comments/abc123/...",
                                    }
                                }
                            ]
                        }
                    }
                ],
                raise_for_status=lambda: None,
            )

        mock_client.get = mock_get

        with patch(
            "app.services.insights.adapters.collectors.reddit.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            collector = RedditCollector(async_db_session, **collector_kwargs(project))
            result = await collector.add_post(
                "https://reddit.com/r/Python/comments/abc123/announcing_aegis_stack"
            )

        assert result.success is True
        assert result.source_key == SourceKeys.REDDIT
        assert result.rows_written == 1

        # Verify metric was written
        metrics = await async_db_session.exec(select(InsightMetric))
        metric_list = metrics.all()
        assert len(metric_list) == 1
        assert metric_list[0].value == 150.0  # upvotes
        assert metric_list[0].metadata_.get("post_id") == "abc123"

        # Verify event was created
        events = await async_db_session.exec(select(InsightEvent))
        event_list = events.all()
        assert len(event_list) == 1
        assert "Python" in event_list[0].description
        assert event_list[0].metadata_.get("post_id") == "abc123"

    @pytest.mark.asyncio
    async def test_add_post_api_error(self, async_db_session: AsyncSession) -> None:
        """HTTP error from Reddit is handled gracefully."""
        import httpx

        await _seed_reddit(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        mock_response = MagicMock(status_code=404)
        error = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=error)

        with patch(
            "app.services.insights.adapters.collectors.reddit.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            collector = RedditCollector(async_db_session, **collector_kwargs(project))
            result = await collector.add_post(
                "https://reddit.com/r/Python/comments/notfound/..."
            )

        assert result.success is False
        assert "Reddit API error" in result.error

    @pytest.mark.asyncio
    async def test_add_post_parse_error(self, async_db_session: AsyncSession) -> None:
        """Malformed Reddit response is handled gracefully."""
        await _seed_reddit(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs):
            # Missing nested structure
            return MagicMock(
                json=lambda: [{"data": {}}],  # Missing children
                raise_for_status=lambda: None,
            )

        mock_client.get = mock_get

        with patch(
            "app.services.insights.adapters.collectors.reddit.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            collector = RedditCollector(async_db_session, **collector_kwargs(project))
            result = await collector.add_post(
                "https://reddit.com/r/Python/comments/abc123/..."
            )

        assert result.success is False
        assert "Failed to parse Reddit response" in result.error

    @pytest.mark.asyncio
    async def test_add_post_deduplication(self, async_db_session: AsyncSession) -> None:
        """Second add_post for same post doesn't duplicate event."""
        await _seed_reddit(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        # Pre-add the post
        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs):
            return MagicMock(
                json=lambda: [
                    {
                        "data": {
                            "children": [
                                {
                                    "data": {
                                        "id": "abc123",
                                        "subreddit": "Python",
                                        "title": "Announcing Aegis Stack",
                                        "ups": 150,
                                        "num_comments": 25,
                                        "view_count": 5000,
                                        "upvote_ratio": 0.95,
                                        "created_utc": 1712900000,
                                        "url": "https://reddit.com/r/Python/comments/abc123/...",
                                    }
                                }
                            ]
                        }
                    }
                ],
                raise_for_status=lambda: None,
            )

        mock_client.get = mock_get

        with patch(
            "app.services.insights.adapters.collectors.reddit.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            collector = RedditCollector(async_db_session, **collector_kwargs(project))
            # First add
            result1 = await collector.add_post(
                "https://reddit.com/r/Python/comments/abc123/announcing_aegis_stack"
            )
            assert result1.success is True

            # Second add with updated stats
            async def mock_get_updated(url: str, **kwargs):
                return MagicMock(
                    json=lambda: [
                        {
                            "data": {
                                "children": [
                                    {
                                        "data": {
                                            "id": "abc123",
                                            "subreddit": "Python",
                                            "title": "Announcing Aegis Stack",
                                            "ups": 200,  # Updated
                                            "num_comments": 35,
                                            "view_count": 7000,
                                            "upvote_ratio": 0.96,
                                            "created_utc": 1712900000,
                                            "url": "https://reddit.com/r/Python/comments/abc123/...",
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                    raise_for_status=lambda: None,
                )

            mock_client.get = mock_get_updated
            result2 = await collector.add_post(
                "https://reddit.com/r/Python/comments/abc123/announcing_aegis_stack"
            )
            assert result2.success is True

        # Verify only 1 event exists (deduped), but 2 metrics
        # (upsert_metric always creates events with period=EVENT)
        events = await async_db_session.exec(
            select(InsightEvent).where(InsightEvent.event_type == "reddit_post")
        )
        event_list = events.all()
        # Should have exactly 1 event due to deduplication in add_post
        assert len(event_list) == 1
        assert event_list[0].metadata_.get("post_id") == "abc123"

    @pytest.mark.asyncio
    async def test_collect_returns_on_demand_message(
        self, async_db_session: AsyncSession
    ) -> None:
        """collect() returns on-demand message."""
        await _seed_reddit(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        collector = RedditCollector(async_db_session, **collector_kwargs(project))
        result = await collector.collect()

        assert result.success is True
        assert "on-demand" in result.error
        assert result.source_key == SourceKeys.REDDIT
