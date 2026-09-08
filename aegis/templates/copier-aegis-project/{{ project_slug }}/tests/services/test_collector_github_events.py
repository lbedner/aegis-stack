"""
Tests for GitHubEventsCollector — ClickHouse-based event collection.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.insights.adapters.collectors.github_events import GitHubEventsCollector
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import InsightMetric, InsightMetricType, InsightSource

from ._collector_fixtures import collector_kwargs, seed_project_for_collector
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_github_events(
    session: AsyncSession,
) -> tuple[InsightSource, dict[str, InsightMetricType]]:
    """Seed github_events source with all metric types."""
    source = InsightSource(
        key=SourceKeys.GITHUB_EVENTS,
        display_name="GitHub Events",
        collection_interval_hours=6,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    metric_types: dict[str, InsightMetricType] = {}
    for key in [
        MetricKeys.FORKS,
        MetricKeys.RELEASES,
        MetricKeys.STAR_EVENTS,
        MetricKeys.ACTIVITY_SUMMARY,
    ]:
        mt = InsightMetricType(
            source_id=source.id,  # type: ignore[arg-type]
            key=key,
            display_name=key.replace("_", " ").title(),
            unit="json" if key == MetricKeys.ACTIVITY_SUMMARY else "count",
        )
        session.add(mt)
        await session.flush()
        metric_types[key] = mt

    return source, metric_types


# ---------------------------------------------------------------------------
# Tests: GitHubEventsCollector
# ---------------------------------------------------------------------------


class TestGitHubEventsCollectorSuccess:
    """Test successful collection."""

    @pytest.mark.asyncio
    async def test_collect_success(self, async_db_session: AsyncSession) -> None:
        """Happy path: collect forks, releases, stars, activity summary."""
        await _seed_github_events(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack")

        # Mock httpx.AsyncClient
        mock_client = AsyncMock()

        async def mock_post(url: str, **kwargs):
            """Mock ClickHouse API responses."""
            content = kwargs.get("content", "")

            if "ForkEvent" in content:
                # Forks: actor, day
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["user1", "2026-04-11"],
                            ["user2", "2026-04-10"],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "ReleaseEvent" in content:
                # Releases: actor, tag, name, day
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["bot", "v1.0.0", "Version 1.0.0", "2026-04-10"],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "WatchEvent" in content:
                # Stars: day, count
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", 5],
                            ["2026-04-10", 3],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            else:  # Activity summary
                # Activity: day, event_type, count
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "PushEvent", 10],
                            ["2026-04-11", "PullRequestEvent", 2],
                            ["2026-04-10", "IssuesEvent", 1],
                        ]
                    },
                    raise_for_status=lambda: None,
                )

        mock_client.post = mock_post

        with patch(
            "app.services.insights.adapters.collectors.github_events.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.github_events.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_GITHUB_TOKEN = ""
                mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
                mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

                collector = GitHubEventsCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is True
        assert result.source_key == SourceKeys.GITHUB_EVENTS
        assert result.rows_written > 0

        # Verify metrics were written
        metrics = await async_db_session.exec(select(InsightMetric))
        assert len(metrics.all()) > 0

    @pytest.mark.asyncio
    async def test_collect_missing_config(self, async_db_session: AsyncSession) -> None:
        """Missing INSIGHT_GITHUB_OWNER or INSIGHT_GITHUB_REPO returns error."""
        await _seed_github_events(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner=None, github_repo=None)

        with patch(
            "app.services.insights.adapters.collectors.github_events.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_OWNER = None
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            collector = GitHubEventsCollector(async_db_session, **collector_kwargs(project))
            result = await collector.collect()

        assert result.success is False
        assert "Missing INSIGHT_GITHUB_OWNER" in result.error

    @pytest.mark.asyncio
    async def test_collect_api_error(self, async_db_session: AsyncSession) -> None:
        """HTTP error from ClickHouse is handled gracefully."""
        await _seed_github_events(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=Exception("ClickHouse connection failed")
        )

        with patch(
            "app.services.insights.adapters.collectors.github_events.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.github_events.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_GITHUB_TOKEN = ""
                mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
                mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

                collector = GitHubEventsCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is False
        assert "GitHub events collection failed" in result.error

    @pytest.mark.asyncio
    async def test_deduplication_forks(self, async_db_session: AsyncSession) -> None:
        """Second collect doesn't duplicate fork rows."""
        source, metric_types = await _seed_github_events(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack")
        forks_type = metric_types[MetricKeys.FORKS]

        # Pre-populate an existing fork
        project_kwargs = {'project_id': project.id} if project is not None else {}
        existing_fork = InsightMetric(
            date=datetime(2026, 4, 11),
            metric_type_id=forks_type.id,  # type: ignore[arg-type]
            value=1.0,
            period=Periods.EVENT,
            metadata_={"actor": "user1", "date": "2026-04-11"},
            **project_kwargs,
        )
        async_db_session.add(existing_fork)
        await async_db_session.commit()

        # Now collect with user1 already in DB
        mock_client = AsyncMock()

        async def mock_post(url: str, **kwargs):
            content = kwargs.get("content", "")
            if "ForkEvent" in content:
                return MagicMock(
                    json=lambda: {
                        "data": [["user1", "2026-04-11"], ["user2", "2026-04-10"]]
                    },
                    raise_for_status=lambda: None,
                )
            elif "ReleaseEvent" in content or "WatchEvent" in content:
                return MagicMock(
                    json=lambda: {"data": []},
                    raise_for_status=lambda: None,
                )
            else:
                return MagicMock(
                    json=lambda: {"data": []},
                    raise_for_status=lambda: None,
                )

        mock_client.post = mock_post

        with patch(
            "app.services.insights.adapters.collectors.github_events.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.github_events.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_GITHUB_TOKEN = ""
                mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
                mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

                collector = GitHubEventsCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is True
        # user1 should be skipped (already in DB), user2 should be new
        assert result.rows_skipped == 1
        assert result.rows_written >= 1

        # Verify only 2 fork rows exist (original + new user2)
        fork_metrics = await async_db_session.exec(
            select(InsightMetric).where(InsightMetric.metric_type_id == forks_type.id)
        )
        fork_count = len(fork_metrics.all())
        assert fork_count == 2
