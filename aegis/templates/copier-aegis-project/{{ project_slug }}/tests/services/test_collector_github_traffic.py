"""
Tests for GitHubTrafficCollector.

Tests the GitHub API integration, response processing, deduplication,
and error handling for the GitHub Traffic insight collector.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.insights.adapters.collectors.github_traffic import GitHubTrafficCollector
from app.services.insights.constants import MetricKeys, SourceKeys
from app.services.insights.models import InsightMetric, InsightMetricType

from ._collector_fixtures import collector_kwargs, seed_project_for_collector
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .test_insights_collectors import _seed_github_traffic

# ---------------------------------------------------------------------------
# Response Fixtures
# ---------------------------------------------------------------------------


CLONES_RESPONSE = {
    "count": 50,
    "uniques": 10,
    "clones": [
        {"timestamp": "2026-04-10T00:00:00Z", "count": 30, "uniques": 6},
        {"timestamp": "2026-04-11T00:00:00Z", "count": 20, "uniques": 4},
    ],
}

VIEWS_RESPONSE = {
    "count": 100,
    "uniques": 25,
    "views": [
        {"timestamp": "2026-04-10T00:00:00Z", "count": 60, "uniques": 15},
        {"timestamp": "2026-04-11T00:00:00Z", "count": 40, "uniques": 10},
    ],
}

REFERRERS_RESPONSE = [
    {"referrer": "Google", "count": 50, "uniques": 10},
    {"referrer": "github.com", "count": 30, "uniques": 8},
]

PATHS_RESPONSE = [
    {
        "path": "/lbedner/aegis-stack",
        "title": "aegis-stack",
        "count": 80,
        "uniques": 20,
    },
    {
        "path": "/lbedner/aegis-stack/issues",
        "title": "Issues",
        "count": 15,
        "uniques": 5,
    },
]


# ---------------------------------------------------------------------------
# Helper: Mock HTTP Responses
# ---------------------------------------------------------------------------


def _create_mock_response(json_data: dict | list) -> MagicMock:
    """Create a mock httpx response with json() and raise_for_status()."""
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Tests: Successful Collection
# ---------------------------------------------------------------------------


class TestGitHubTrafficCollectorSuccess:
    """Tests for successful GitHub API data collection."""

    @pytest.mark.asyncio
    async def test_collect_success(self, async_db_session: AsyncSession) -> None:
        """Successful collection processes all 4 API endpoints and stores data."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        # Mock settings
        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            # Mock httpx.AsyncClient
            mock_client = AsyncMock()
            mock_client.get.side_effect = [
                _create_mock_response(CLONES_RESPONSE),
                _create_mock_response(VIEWS_RESPONSE),
                _create_mock_response(REFERRERS_RESPONSE),
                _create_mock_response(PATHS_RESPONSE),
            ]
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await collector.collect()

        assert result.success is True
        assert result.source_key == SourceKeys.GITHUB_TRAFFIC
        # 2 clones entries * 2 metrics (clones + unique_cloners) = 4
        # 2 views entries * 2 metrics (views + unique_visitors) = 4
        # 1 referrers row + 1 paths row = 2
        # 4 server-side 14d rolling totals (clones_14d, clones_14d_unique,
        #   views_14d, views_14d_unique) — one row each, latest day = 4
        # Total = 14
        assert result.rows_written == 14
        assert result.rows_skipped == 0
        assert result.error is None

        # Verify metrics were written to database
        clones_metric = await async_db_session.exec(
            select(InsightMetric)
            .join(InsightMetricType)
            .where(InsightMetricType.key == MetricKeys.CLONES)
        )
        assert len(clones_metric.all()) == 2  # One for each day


# ---------------------------------------------------------------------------
# Tests: Missing Configuration
# ---------------------------------------------------------------------------


class TestGitHubTrafficCollectorMissingConfig:
    """Tests for missing or incomplete settings."""

    @pytest.mark.asyncio
    async def test_collect_missing_token(self, async_db_session: AsyncSession) -> None:
        """Collection fails when INSIGHT_GITHUB_TOKEN is missing."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner='lbedner', github_repo='aegis-stack', github_token=None)

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = ""
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            result = await collector.collect()

        assert result.success is False
        assert "Missing" in result.error
        assert result.rows_written == 0
        assert result.rows_skipped == 0

    @pytest.mark.asyncio
    async def test_collect_missing_owner(self, async_db_session: AsyncSession) -> None:
        """Collection fails when INSIGHT_GITHUB_OWNER is missing."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner=None, github_repo='aegis-stack', github_token='token123')

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = ""
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            result = await collector.collect()

        assert result.success is False
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_collect_missing_repo(self, async_db_session: AsyncSession) -> None:
        """Collection fails when INSIGHT_GITHUB_REPO is missing."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner='lbedner', github_repo=None, github_token='token123')

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = ""

            result = await collector.collect()

        assert result.success is False
        assert "Missing" in result.error


# ---------------------------------------------------------------------------
# Tests: Deduplication (Idempotency)
# ---------------------------------------------------------------------------


class TestGitHubTrafficCollectorDeduplication:
    """Tests for deduplication behavior on repeated collections."""

    @pytest.mark.asyncio
    async def test_collect_deduplication(self, async_db_session: AsyncSession) -> None:
        """Running collect twice with same data skips duplicates on second run."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            # First collection
            mock_client = AsyncMock()
            mock_client.get.side_effect = [
                _create_mock_response(CLONES_RESPONSE),
                _create_mock_response(VIEWS_RESPONSE),
                _create_mock_response(REFERRERS_RESPONSE),
                _create_mock_response(PATHS_RESPONSE),
            ]
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                result1 = await collector.collect()

            assert result1.success is True
            # Same total as test_collect_success (10 base + 4 14d rolling).
            assert result1.rows_written == 14
            assert result1.rows_skipped == 0

            # Second collection with same data
            mock_client2 = AsyncMock()
            mock_client2.get.side_effect = [
                _create_mock_response(CLONES_RESPONSE),
                _create_mock_response(VIEWS_RESPONSE),
                _create_mock_response(REFERRERS_RESPONSE),
                _create_mock_response(PATHS_RESPONSE),
            ]
            mock_client2.__aenter__.return_value = mock_client2
            mock_client2.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client2):
                result2 = await collector.collect()

            assert result2.success is True
            assert result2.rows_written == 0  # All rows already exist
            assert result2.rows_skipped == 14


# ---------------------------------------------------------------------------
# Tests: API Errors
# ---------------------------------------------------------------------------


class TestGitHubTrafficCollectorAPIErrors:
    """Tests for HTTP errors and malformed responses."""

    @pytest.mark.asyncio
    async def test_collect_api_error_403(self, async_db_session: AsyncSession) -> None:
        """Collection fails gracefully on HTTP 403 error."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "invalid-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            # Mock a 403 response
            import httpx

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 403
            mock_response.text = "API rate limit exceeded"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403 Forbidden",
                request=MagicMock(),
                response=mock_response,
            )

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await collector.collect()

        assert result.success is False
        assert "403" in result.error
        assert result.rows_written == 0

    @pytest.mark.asyncio
    async def test_collect_api_error_500(self, async_db_session: AsyncSession) -> None:
        """Collection fails gracefully on HTTP 500 error."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            import httpx

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 Internal Server Error",
                request=MagicMock(),
                response=mock_response,
            )

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await collector.collect()

        assert result.success is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_collect_generic_exception(
        self, async_db_session: AsyncSession
    ) -> None:
        """Collection fails gracefully on unexpected exceptions."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Network timeout")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await collector.collect()

        assert result.success is False
        assert "Network timeout" in result.error


# ---------------------------------------------------------------------------
# Tests: Data Processing
# ---------------------------------------------------------------------------


class TestGitHubTrafficCollectorProcessing:
    """Tests for individual data processing methods."""

    @pytest.mark.asyncio
    async def test_process_clones(self, async_db_session: AsyncSession) -> None:
        """_process_clones correctly parses timestamps and creates metrics."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        written, skipped = await collector._process_clones(CLONES_RESPONSE)

        # 2 clone entries * 2 metrics (clones + unique_cloners) = 4
        assert written == 4
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_process_views(self, async_db_session: AsyncSession) -> None:
        """_process_views correctly parses timestamps and creates metrics."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        written, skipped = await collector._process_views(VIEWS_RESPONSE)

        # 2 view entries * 2 metrics (views + unique_visitors) = 4
        assert written == 4
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_process_referrers(self, async_db_session: AsyncSession) -> None:
        """_process_referrers creates single snapshot row with metadata."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        written, skipped = await collector._process_referrers(REFERRERS_RESPONSE)

        # Single snapshot row for all referrers
        assert written == 1
        assert skipped == 0

        # Verify metadata was stored
        result = await async_db_session.exec(
            select(InsightMetric)
            .join(InsightMetricType)
            .where(InsightMetricType.key == MetricKeys.REFERRERS)
        )
        metrics = result.all()
        assert len(metrics) == 1
        assert metrics[0].metadata_ is not None
        assert "Google" in metrics[0].metadata_

    @pytest.mark.asyncio
    async def test_process_popular_paths(self, async_db_session: AsyncSession) -> None:
        """_process_popular_paths creates single snapshot row with path metadata."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        written, skipped = await collector._process_popular_paths(PATHS_RESPONSE)

        # Single snapshot row for all paths
        assert written == 1
        assert skipped == 0

        # Verify metadata structure
        result = await async_db_session.exec(
            select(InsightMetric)
            .join(InsightMetricType)
            .where(InsightMetricType.key == MetricKeys.POPULAR_PATHS)
        )
        metrics = result.all()
        assert len(metrics) == 1
        assert metrics[0].metadata_ is not None
        assert "paths" in metrics[0].metadata_


# ---------------------------------------------------------------------------
# Tests: HTTP Headers and Authorization
# ---------------------------------------------------------------------------


class TestGitHubTrafficCollectorHeaders:
    """Tests for correct HTTP headers and authentication."""

    @pytest.mark.asyncio
    async def test_collect_sets_correct_headers(
        self, async_db_session: AsyncSession
    ) -> None:
        """Collection sets correct GitHub API headers."""
        await _seed_github_traffic(async_db_session)
        # Token here MUST match the value the test asserts on below.
        project = await seed_project_for_collector(
            async_db_session,
            github_owner="lbedner",
            github_repo="aegis-stack",
            github_token="test-token-123",
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token-123"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            mock_client = AsyncMock()
            mock_client.get.side_effect = [
                _create_mock_response(CLONES_RESPONSE),
                _create_mock_response(VIEWS_RESPONSE),
                _create_mock_response(REFERRERS_RESPONSE),
                _create_mock_response(PATHS_RESPONSE),
            ]
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client_class.return_value = mock_client
                await collector.collect()

                # Verify AsyncClient was called with correct headers
                call_kwargs = mock_client_class.call_args[1]
                headers = call_kwargs.get("headers", {})
                assert "Authorization" in headers
                assert "Bearer test-token-123" in headers["Authorization"]
                assert "application/vnd.github+json" in headers["Accept"]
                assert "2022-11-28" in headers["X-GitHub-Api-Version"]

    @pytest.mark.asyncio
    async def test_collect_uses_correct_urls(
        self, async_db_session: AsyncSession
    ) -> None:
        """Collection requests correct GitHub API endpoints."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session, github_owner="lbedner", github_repo="aegis-stack", github_token="token123")

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with patch(
            "app.services.insights.adapters.collectors.base.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_GITHUB_TOKEN = "test-token"
            mock_settings.INSIGHT_GITHUB_OWNER = "lbedner"
            mock_settings.INSIGHT_GITHUB_REPO = "aegis-stack"

            mock_client = AsyncMock()
            mock_client.get.side_effect = [
                _create_mock_response(CLONES_RESPONSE),
                _create_mock_response(VIEWS_RESPONSE),
                _create_mock_response(REFERRERS_RESPONSE),
                _create_mock_response(PATHS_RESPONSE),
            ]
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                await collector.collect()

                # Verify all 4 endpoints were called
                assert mock_client.get.call_count == 4
                calls = [call[0][0] for call in mock_client.get.call_args_list]
                assert any("traffic/clones" in call for call in calls)
                assert any("traffic/views" in call for call in calls)
                assert any("popular/referrers" in call for call in calls)
                assert any("popular/paths" in call for call in calls)
