"""
Tests for GitHubStarsCollector -- GitHub REST API stargazers collection.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.insights.adapters.collectors.github_stars import GitHubStarsCollector
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import InsightMetric, InsightMetricType, InsightSource

from ._collector_fixtures import collector_kwargs, seed_project_for_collector
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_github_stars(
    session: AsyncSession,
) -> tuple[InsightSource, dict[str, InsightMetricType]]:
    """Seed github_stars source with all metric types."""
    source = InsightSource(
        key=SourceKeys.GITHUB_STARS,
        display_name="GitHub Stars",
        collection_interval_hours=24,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    metric_types: dict[str, InsightMetricType] = {}
    mt = InsightMetricType(
        source_id=source.id,  # type: ignore[arg-type]
        key=MetricKeys.NEW_STAR,
        display_name="New Star",
        unit="count",
    )
    session.add(mt)
    await session.flush()
    metric_types[MetricKeys.NEW_STAR] = mt

    return source, metric_types


# ---------------------------------------------------------------------------
# Tests: GitHubStarsCollector
# ---------------------------------------------------------------------------


class TestGitHubStarsCollectorSuccess:
    """Test successful collection."""

    @pytest.mark.asyncio
    async def test_collect_success(self, async_db_session: AsyncSession) -> None:
        """Happy path: collect stargazers with profiles."""
        await _seed_github_stars(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        # Mock httpx.AsyncClient
        mock_client = AsyncMock()

        # Stargazer data for pagination
        stargazers_page_1 = [
            {
                "user": {"login": "user1"},
                "starred_at": "2026-04-11T10:30:00Z",
            },
            {
                "user": {"login": "user2"},
                "starred_at": "2026-04-10T15:00:00Z",
            },
        ]

        # User profile responses
        async def mock_get(url: str, **kwargs):
            if "stargazers" in url:
                # Return paginated stargazers
                page = kwargs.get("params", {}).get("page", 1)
                if page == 1:
                    return MagicMock(
                        json=lambda: stargazers_page_1,
                        raise_for_status=lambda: None,
                    )
                else:
                    return MagicMock(
                        json=lambda: [],
                        raise_for_status=lambda: None,
                    )
            else:  # User profile endpoint
                username = url.split("/")[-1]
                return MagicMock(
                    json=lambda: {
                        "login": username,
                        "name": f"User {username}",
                        "location": "Test City",
                        "followers": 10,
                        "following": 5,
                        "public_repos": 20,
                        "starred_repos_count": 100,
                        "created_at": "2010-01-01T00:00:00Z",
                    },
                    raise_for_status=lambda: None,
                )

        mock_client.get = mock_get

        with patch(
            "app.services.insights.adapters.collectors.github_stars.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.base.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_GITHUB_TOKEN = "token123"
                mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
                mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

                collector = GitHubStarsCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is True
        assert result.source_key == SourceKeys.GITHUB_STARS
        assert result.rows_written > 0

        # Verify metrics were written
        metrics = await async_db_session.exec(select(InsightMetric))
        metric_list = metrics.all()
        assert len(metric_list) > 0
        # Check metadata has profile info
        for metric in metric_list:
            if metric.metadata_:
                assert "username" in metric.metadata_

    @pytest.mark.asyncio
    async def test_collect_missing_config(self, async_db_session: AsyncSession) -> None:
        """Missing token/owner/repo returns error."""
        await _seed_github_stars(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner=None, github_repo=None, github_token=None)

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = None
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            collector = GitHubStarsCollector(async_db_session, **collector_kwargs(project))
            result = await collector.collect()

        assert result.success is False
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_collect_api_error(self, async_db_session: AsyncSession) -> None:
        """HTTP error from GitHub API is handled gracefully."""
        import httpx

        await _seed_github_stars(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        mock_response = MagicMock(status_code=403, text="Forbidden")
        error = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=error)

        with patch(
            "app.services.insights.adapters.collectors.github_stars.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.base.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_GITHUB_TOKEN = "token123"
                mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
                mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

                collector = GitHubStarsCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is False
        assert "GitHub API error" in result.error

    @pytest.mark.asyncio
    async def test_deduplication(self, async_db_session: AsyncSession) -> None:
        """Second collect doesn't duplicate existing stars."""
        source, metric_types = await _seed_github_stars(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")
        star_type = metric_types[MetricKeys.NEW_STAR]

        # Pre-populate star #1
        project_kwargs = {'project_id': project.id} if project is not None else {}
        existing_star = InsightMetric(
            date=datetime(2026, 4, 11),
            metric_type_id=star_type.id,  # type: ignore[arg-type]
            value=1.0,  # star number 1
            period=Periods.EVENT,
            metadata_={
                "username": "user1",
                "followers": 10,
                "account_age_years": 15.0,
            },
            **project_kwargs,
        )
        async_db_session.add(existing_star)
        await async_db_session.commit()

        # Collect again with star #1 already in DB
        stargazers_page_1 = [
            {
                "user": {"login": "user1"},
                "starred_at": "2026-04-11T10:30:00Z",
            },
            {
                "user": {"login": "user2"},
                "starred_at": "2026-04-10T15:00:00Z",
            },
        ]

        async def mock_get(url: str, **kwargs):
            if "stargazers" in url:
                page = kwargs.get("params", {}).get("page", 1)
                if page == 1:
                    return MagicMock(
                        json=lambda: stargazers_page_1,
                        raise_for_status=lambda: None,
                    )
                else:
                    return MagicMock(
                        json=lambda: [],
                        raise_for_status=lambda: None,
                    )
            else:
                return MagicMock(
                    json=lambda: {
                        "login": "user1",
                        "followers": 10,
                        "created_at": "2010-01-01T00:00:00Z",
                    },
                    raise_for_status=lambda: None,
                )

        mock_client = AsyncMock()
        mock_client.get = mock_get

        with patch(
            "app.services.insights.adapters.collectors.github_stars.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.base.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_GITHUB_TOKEN = "token123"
                mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
                mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

                collector = GitHubStarsCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is True
        # Star #1 skipped (already in DB), star #2 new
        assert result.rows_skipped == 1
        assert result.rows_written >= 1

        # Verify only 2 star rows (original + new)
        star_metrics = await async_db_session.exec(
            select(InsightMetric).where(InsightMetric.metric_type_id == star_type.id)
        )
        assert len(star_metrics.all()) == 2
