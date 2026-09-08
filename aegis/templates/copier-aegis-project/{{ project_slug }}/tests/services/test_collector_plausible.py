"""
Tests for PlausibleCollector -- Plausible Analytics collection.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.insights.adapters.collectors.plausible import PlausibleCollector
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import InsightMetric, InsightMetricType, InsightSource

from ._collector_fixtures import collector_kwargs, seed_project_for_collector
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_plausible(
    session: AsyncSession,
) -> tuple[InsightSource, dict[str, InsightMetricType]]:
    """Seed plausible source with all metric types."""
    source = InsightSource(
        key=SourceKeys.PLAUSIBLE,
        display_name="Plausible Analytics",
        collection_interval_hours=24,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    metric_types: dict[str, InsightMetricType] = {}
    for key in [
        MetricKeys.VISITORS,
        MetricKeys.PAGEVIEWS,
        MetricKeys.AVG_DURATION,
        MetricKeys.BOUNCE_RATE,
        MetricKeys.TOP_PAGES,
        MetricKeys.TOP_COUNTRIES,
        MetricKeys.TOP_SOURCES,
    ]:
        mt = InsightMetricType(
            source_id=source.id,  # type: ignore[arg-type]
            key=key,
            display_name=key.replace("_", " ").title(),
            unit="json" if "top_" in key else "count",
        )
        session.add(mt)
        await session.flush()
        metric_types[key] = mt

    return source, metric_types


# ---------------------------------------------------------------------------
# Tests: PlausibleCollector
# ---------------------------------------------------------------------------


class TestPlausibleCollectorSuccess:
    """Test successful collection."""

    @pytest.mark.asyncio
    async def test_collect_success(self, async_db_session: AsyncSession) -> None:
        """Happy path: collect visitor metrics and page engagement."""
        await _seed_plausible(async_db_session)
        project = await seed_project_for_collector(async_db_session, plausible_api_key="apikey123", plausible_site="docs.example.com")

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs):
            """Mock Plausible v1 GET endpoints (timeseries + breakdown)."""
            if "timeseries" in url:
                return MagicMock(
                    json=lambda: {
                        "results": [
                            {
                                "date": "2026-04-11",
                                "visitors": 100,
                                "pageviews": 250,
                                "visit_duration": 45.5,
                                "bounce_rate": 35.0,
                            },
                            {
                                "date": "2026-04-10",
                                "visitors": 80,
                                "pageviews": 200,
                                "visit_duration": 42.0,
                                "bounce_rate": 40.0,
                            },
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "breakdown" in url:
                params = kwargs.get("params", {})
                prop = params.get("property", "")
                if "visit:source" in prop:
                    return MagicMock(
                        json=lambda: {
                            "results": [
                                {"source": "Direct / None", "visitors": 50},
                                {"source": "github.com", "visitors": 30},
                            ]
                        },
                        raise_for_status=lambda: None,
                    )
                # Default: visit:country
                return MagicMock(
                    json=lambda: {
                        "results": [
                            {"country": "United States", "visitors": 70},
                            {"country": "Canada", "visitors": 30},
                        ]
                    },
                    raise_for_status=lambda: None,
                )

        async def mock_post(url: str, **kwargs):
            """Mock Plausible v2 POST /query (page engagement breakdown)."""
            return MagicMock(
                json=lambda: {
                    "results": [
                        # `dimensions` is a list per request order; `metrics`
                        # matches PAGE_METRICS = [visitors, pageviews,
                        # bounce_rate, time_on_page, scroll_depth].
                        {
                            "dimensions": ["/docs"],
                            "metrics": [60, 150, 35.0, 120.0, 75.0],
                        },
                        {
                            "dimensions": ["/"],
                            "metrics": [40, 100, 40.0, 30.0, 50.0],
                        },
                    ]
                },
                raise_for_status=lambda: None,
            )

        mock_client.get = mock_get
        mock_client.post = mock_post

        with patch(
            "app.services.insights.adapters.collectors.plausible.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.plausible.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PLAUSIBLE_API_KEY = "apikey123"
                mock_settings.INSIGHT_PLAUSIBLE_SITES = "docs.example.com"

                collector = PlausibleCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect(lookback_days=1)

        assert result.success is True
        assert result.source_key == SourceKeys.PLAUSIBLE
        assert result.rows_written > 0

        # Verify metrics were written
        metrics = await async_db_session.exec(select(InsightMetric))
        metric_list = metrics.all()
        assert len(metric_list) > 0

    @pytest.mark.asyncio
    async def test_collect_missing_config(self, async_db_session: AsyncSession) -> None:
        """Missing API key or sites returns ``skipped=True`` — not a failure.

        Plausible is opt-in; unconfigured sources should render as a
        yellow notice in the CLI / job runner, not red error.
        """
        await _seed_plausible(async_db_session)
        # Project with NO credentials — verifies the "skipped (not configured)" path.
        project = await seed_project_for_collector(
            async_db_session,
            plausible_api_key=None,
            plausible_site=None,
        )

        with patch(
            "app.services.insights.adapters.collectors.plausible.settings"
        ) as mock_settings:
            mock_settings.INSIGHT_PLAUSIBLE_API_KEY = None
            mock_settings.INSIGHT_PLAUSIBLE_SITES = "docs.example.com"

            collector = PlausibleCollector(async_db_session, **collector_kwargs(project))
            result = await collector.collect()

        assert result.success is True
        assert result.skipped is True
        assert "Not configured" in result.error

    @pytest.mark.asyncio
    async def test_collect_api_error(self, async_db_session: AsyncSession) -> None:
        """HTTP error from Plausible is handled gracefully."""
        import httpx

        await _seed_plausible(async_db_session)
        project = await seed_project_for_collector(async_db_session, plausible_api_key="apikey123", plausible_site="docs.example.com")

        mock_response = MagicMock(status_code=401)
        error = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=error)

        with patch(
            "app.services.insights.adapters.collectors.plausible.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.plausible.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PLAUSIBLE_API_KEY = "apikey123"
                mock_settings.INSIGHT_PLAUSIBLE_SITES = "docs.example.com"

                collector = PlausibleCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is False
        assert "Plausible API error" in result.error

    @pytest.mark.asyncio
    async def test_deduplication(self, async_db_session: AsyncSession) -> None:
        """Second collect doesn't duplicate existing daily rows."""
        source, metric_types = await _seed_plausible(async_db_session)
        project = await seed_project_for_collector(async_db_session, plausible_api_key="apikey123", plausible_site="docs.example.com")
        visitors_type = metric_types[MetricKeys.VISITORS]

        # Pre-populate a visitors row
        project_kwargs = {"project_id": project.id} if project is not None else {}
        existing_visitors = InsightMetric(
            date=datetime(2026, 4, 11),
            metric_type_id=visitors_type.id,  # type: ignore[arg-type]
            value=100.0,
            period=Periods.DAILY,
            metadata_={"site": "docs.example.com"},
            **project_kwargs,
        )
        async_db_session.add(existing_visitors)
        await async_db_session.commit()

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs):
            if "timeseries" in url:
                return MagicMock(
                    json=lambda: {
                        "results": [
                            {
                                "date": "2026-04-11",
                                "visitors": 100,
                                "pageviews": 250,
                                "visit_duration": 45.5,
                                "bounce_rate": 35.0,
                            },
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "breakdown" in url:
                return MagicMock(
                    json=lambda: {"results": []},
                    raise_for_status=lambda: None,
                )

        async def mock_post(url: str, **kwargs):
            return MagicMock(
                json=lambda: {"results": []},
                raise_for_status=lambda: None,
            )

        mock_client.get = mock_get
        mock_client.post = mock_post

        with patch(
            "app.services.insights.adapters.collectors.plausible.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.plausible.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PLAUSIBLE_API_KEY = "apikey123"
                mock_settings.INSIGHT_PLAUSIBLE_SITES = "docs.example.com"

                collector = PlausibleCollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect(lookback_days=1)

        assert result.success is True
        # The visitors row for 2026-04-11 should be skipped (already exists)
        assert result.rows_skipped > 0

    @pytest.mark.asyncio
    async def test_lookback_days(self, async_db_session: AsyncSession) -> None:
        """Lookback parameter affects query date range."""
        await _seed_plausible(async_db_session)
        project = await seed_project_for_collector(async_db_session, plausible_api_key="apikey123", plausible_site="docs.example.com")

        captured_requests: list[dict] = []

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs):
            captured_requests.append(kwargs)
            if "timeseries" in url:
                return MagicMock(
                    json=lambda: {"results": []},
                    raise_for_status=lambda: None,
                )
            else:
                return MagicMock(
                    json=lambda: {"results": []},
                    raise_for_status=lambda: None,
                )

        mock_client.get = mock_get

        with patch(
            "app.services.insights.adapters.collectors.plausible.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.plausible.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PLAUSIBLE_API_KEY = "apikey123"
                mock_settings.INSIGHT_PLAUSIBLE_SITES = "docs.example.com"

                collector = PlausibleCollector(async_db_session, **collector_kwargs(project))
                await collector.collect(lookback_days=30)

        # Check that timeseries request has date range parameter
        timeseries_requests = [
            r
            for r in captured_requests
            if r.get("params", {}).get("period") == "custom"
        ]
        assert len(timeseries_requests) > 0
        # The date parameter should have a range
        date_param = timeseries_requests[0].get("params", {}).get("date", "")
        assert "," in date_param, (
            f"Expected date range like 'YYYY-MM-DD,YYYY-MM-DD', got {date_param}"
        )
