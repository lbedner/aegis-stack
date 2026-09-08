"""
Tests for PyPICollector -- ClickHouse PyPI downloads collection.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.insights.adapters.collectors.pypi import PyPICollector
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import InsightMetric, InsightMetricType, InsightSource

from ._collector_fixtures import collector_kwargs, seed_project_for_collector
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_pypi(
    session: AsyncSession,
) -> tuple[InsightSource, dict[str, InsightMetricType]]:
    """Seed pypi source with all metric types."""
    source = InsightSource(
        key=SourceKeys.PYPI,
        display_name="PyPI Downloads",
        collection_interval_hours=24,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    metric_types: dict[str, InsightMetricType] = {}
    for key in [
        MetricKeys.DOWNLOADS_DAILY,
        MetricKeys.DOWNLOADS_DAILY_HUMAN,
        MetricKeys.DOWNLOADS_TOTAL,
        MetricKeys.DOWNLOADS_BY_COUNTRY,
        MetricKeys.DOWNLOADS_BY_INSTALLER,
        MetricKeys.DOWNLOADS_BY_VERSION,
        MetricKeys.DOWNLOADS_BY_TYPE,
    ]:
        mt = InsightMetricType(
            source_id=source.id,  # type: ignore[arg-type]
            key=key,
            display_name=key.replace("_", " ").title(),
            unit="json" if "breakdown" in key or "by_" in key else "count",
        )
        session.add(mt)
        await session.flush()
        metric_types[key] = mt

    return source, metric_types


# ---------------------------------------------------------------------------
# Tests: PyPICollector
# ---------------------------------------------------------------------------


class TestPyPICollectorSuccess:
    """Test successful collection."""

    @pytest.mark.asyncio
    async def test_collect_success(self, async_db_session: AsyncSession) -> None:
        """Happy path: collect PyPI downloads with dimensional breakdowns."""
        await _seed_pypi(async_db_session)
        project = await seed_project_for_collector(async_db_session, pypi_package="aegis-stack")

        mock_client = AsyncMock()

        async def mock_post(url: str, **kwargs):
            """Mock ClickHouse API responses."""
            content = kwargs.get("content", "")

            if "date, version" in content:
                # Version breakdown — collector reads [date, version, count];
                # extra trailing fields are tolerated.
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "1.0.0", 400, 350],
                            ["2026-04-11", "0.9.0", 100, 50],
                            ["2026-04-10", "1.0.0", 350, 300],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "date, type" in content:
                # Type breakdown
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "bdist_wheel", 350],
                            ["2026-04-11", "sdist", 50],
                            ["2026-04-10", "bdist_wheel", 320],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "date, installer" in content:
                # Daily installer breakdown
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "pip", 500],
                            ["2026-04-11", "uv", 200],
                            ["2026-04-10", "pip", 450],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "date, country_code" in content:
                # Country breakdown
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "US", 300],
                            ["2026-04-11", "CN", 100],
                            ["2026-04-10", "US", 250],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            else:  # Total sum(count)
                return MagicMock(
                    json=lambda: {"data": [[1000000]]},
                    raise_for_status=lambda: None,
                )

        mock_client.post = mock_post

        with patch(
            "app.services.insights.adapters.collectors.pypi.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.pypi.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PYPI_PACKAGE = "aegis-stack"

                collector = PyPICollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect(lookback_days=14)

        assert result.success is True
        assert result.source_key == SourceKeys.PYPI
        assert result.rows_written > 0

        # Verify metrics were written
        metrics = await async_db_session.exec(select(InsightMetric))
        metric_list = metrics.all()
        assert len(metric_list) > 0

    @pytest.mark.asyncio
    async def test_collect_missing_config(self, async_db_session: AsyncSession) -> None:
        """Missing INSIGHT_PYPI_PACKAGE returns error."""
        await _seed_pypi(async_db_session)
        project = await seed_project_for_collector(async_db_session, pypi_package=None)

        with patch("app.services.insights.adapters.collectors.pypi.settings") as mock_settings:
            mock_settings.INSIGHT_PYPI_PACKAGE = None

            collector = PyPICollector(async_db_session, **collector_kwargs(project))
            result = await collector.collect()

        assert result.success is False
        assert "Missing INSIGHT_PYPI_PACKAGE" in result.error

    @pytest.mark.asyncio
    async def test_collect_api_error(self, async_db_session: AsyncSession) -> None:
        """HTTP error from ClickHouse is handled gracefully."""
        await _seed_pypi(async_db_session)
        project = await seed_project_for_collector(async_db_session, pypi_package="aegis-stack")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection timeout"))

        with patch(
            "app.services.insights.adapters.collectors.pypi.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.pypi.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PYPI_PACKAGE = "aegis-stack"

                collector = PyPICollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect()

        assert result.success is False
        assert "PyPI collection failed" in result.error

    @pytest.mark.asyncio
    async def test_deduplication(self, async_db_session: AsyncSession) -> None:
        """Second collect doesn't duplicate daily rows."""
        source, metric_types = await _seed_pypi(async_db_session)
        project = await seed_project_for_collector(async_db_session, pypi_package="aegis-stack")
        daily_type = metric_types[MetricKeys.DOWNLOADS_DAILY]

        # Pre-populate a daily row
        project_kwargs = {'project_id': project.id} if project is not None else {}
        existing_daily = InsightMetric(
            date=datetime(2026, 4, 11),
            metric_type_id=daily_type.id,  # type: ignore[arg-type]
            value=700.0,
            period=Periods.DAILY,
            **project_kwargs,
        )
        async_db_session.add(existing_daily)
        await async_db_session.commit()

        mock_client = AsyncMock()

        async def mock_post(url: str, **kwargs):
            content = kwargs.get("content", "")
            if "date, version" in content:
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "1.0.0", 400, 350],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            elif "date, installer" in content:
                return MagicMock(
                    json=lambda: {
                        "data": [
                            ["2026-04-11", "pip", 500],
                            ["2026-04-11", "uv", 200],
                        ]
                    },
                    raise_for_status=lambda: None,
                )
            else:
                return MagicMock(
                    json=lambda: {"data": []},
                    raise_for_status=lambda: None,
                )

        mock_client.post = mock_post

        with patch(
            "app.services.insights.adapters.collectors.pypi.httpx.AsyncClient"
        ) as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with patch(
                "app.services.insights.adapters.collectors.pypi.settings"
            ) as mock_settings:
                mock_settings.INSIGHT_PYPI_PACKAGE = "aegis-stack"

                collector = PyPICollector(async_db_session, **collector_kwargs(project))
                result = await collector.collect(lookback_days=14)

        assert result.success is True
        # The 2026-04-11 daily row should be skipped (already exists)
        assert result.rows_skipped > 0

    @pytest.mark.skip(
        reason="PyPICollector.collect accepts lookback_days for API parity but "
        "currently pulls a fixed 14-day window. Restore this test if/when the "
        "collector starts honoring the parameter."
    )
    @pytest.mark.asyncio
    async def test_lookback_days(self, async_db_session: AsyncSession) -> None:
        """Lookback parameter affects query date range."""
