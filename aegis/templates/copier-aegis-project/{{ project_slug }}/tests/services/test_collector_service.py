"""
Tests for CollectorService orchestration layer.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from app.services.insights.adapters.collectors.collection import CollectorService
from app.services.insights.adapters.collectors.base import CollectionResult
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import (
    InsightMetric,
    InsightMetricType,
    InsightSource,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from ._collector_fixtures import collector_kwargs, seed_project_for_collector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_source(
    session: AsyncSession,
    key: str = SourceKeys.GITHUB_TRAFFIC,
    enabled: bool = True,
) -> InsightSource:
    source = InsightSource(
        key=key,
        display_name="Test Source",
        collection_interval_hours=6,
        enabled=enabled,
    )
    session.add(source)
    await session.flush()
    return source


async def _seed_metric_type(
    session: AsyncSession,
    source: InsightSource,
    key: str = MetricKeys.CLONES,
) -> InsightMetricType:
    mt = InsightMetricType(
        source_id=source.id,  # type: ignore[arg-type]
        key=key,
        display_name=key.replace("_", " ").title(),
        unit="count",
    )
    session.add(mt)
    await session.flush()
    return mt


# ---------------------------------------------------------------------------
# Tests: collect_source
# ---------------------------------------------------------------------------


class TestCollectSource:
    @pytest.mark.asyncio
    async def test_collect_unknown_source(self, async_db_session: AsyncSession) -> None:
        """Unknown source key returns error CollectionResult."""
        service = CollectorService(async_db_session)
        result = await service.collect_source("nonexistent_source")

        assert result.success is False
        assert "No collector registered" in (result.error or "")

    @pytest.mark.asyncio
    async def test_collect_source_not_in_db(
        self, async_db_session: AsyncSession
    ) -> None:
        """Source key registered but not seeded in DB returns error."""
        service = CollectorService(async_db_session)
        result = await service.collect_source(SourceKeys.GITHUB_TRAFFIC)

        assert result.success is False
        assert "not found in database" in (result.error or "")

    @pytest.mark.asyncio
    async def test_collect_disabled_source(
        self, async_db_session: AsyncSession
    ) -> None:
        """Disabled source returns error."""
        await _seed_source(async_db_session, SourceKeys.GITHUB_TRAFFIC, enabled=False)

        service = CollectorService(async_db_session)
        result = await service.collect_source(SourceKeys.GITHUB_TRAFFIC)

        assert result.success is False
        assert "disabled" in (result.error or "")

    @pytest.mark.asyncio
    @patch("app.services.insights.adapters.collectors.base.settings")
    async def test_collect_updates_last_collected_at(
        self, mock_settings: AsyncMock, async_db_session: AsyncSession
    ) -> None:
        """Successful collection updates source.last_collected_at."""
        mock_settings.INSIGHT_GITHUB_TOKEN = ""
        mock_settings.INSIGHT_GITHUB_OWNER = ""
        mock_settings.INSIGHT_GITHUB_REPO = ""

        source = await _seed_source(async_db_session, SourceKeys.GITHUB_TRAFFIC)
        assert source.last_collected_at is None

        # The collector will fail due to missing config, but that's a success=False path
        # so last_collected_at won't be updated. We need a success path.
        # Patch the collector's collect method directly for a clean test.
        with patch(
            "app.services.insights.adapters.collectors.collection.COLLECTOR_REGISTRY",
            {SourceKeys.GITHUB_TRAFFIC: _make_mock_collector_cls(success=True)},
        ):
            service = CollectorService(async_db_session)
            result = await service.collect_source(SourceKeys.GITHUB_TRAFFIC)

            assert result.success is True

            # Refresh the source from DB
            await async_db_session.refresh(source)
            assert source.last_collected_at is not None


# ---------------------------------------------------------------------------
# Tests: collect_all
# ---------------------------------------------------------------------------


class TestCollectAll:
    @pytest.mark.asyncio
    async def test_collect_all_runs_enabled_sources(
        self, async_db_session: AsyncSession
    ) -> None:
        """collect_all runs collectors for all enabled sources."""
        await _seed_source(async_db_session, SourceKeys.GITHUB_TRAFFIC, enabled=True)
        await _seed_source(async_db_session, SourceKeys.PYPI, enabled=True)
        await _seed_source(async_db_session, SourceKeys.REDDIT, enabled=False)

        mock_cls = _make_mock_collector_cls(success=True)
        registry = {
            SourceKeys.GITHUB_TRAFFIC: mock_cls,
            SourceKeys.PYPI: mock_cls,
            SourceKeys.REDDIT: mock_cls,
        }

        with patch(
            "app.services.insights.adapters.collectors.collection.COLLECTOR_REGISTRY", registry
        ):
            service = CollectorService(async_db_session)
            results = await service.collect_all()

        # Only enabled sources should have results
        assert SourceKeys.GITHUB_TRAFFIC in results
        assert SourceKeys.PYPI in results
        assert SourceKeys.REDDIT not in results

    @pytest.mark.asyncio
    async def test_collect_all_empty_db(self, async_db_session: AsyncSession) -> None:
        """collect_all with no sources returns empty dict."""
        service = CollectorService(async_db_session)
        results = await service.collect_all()
        assert results == {}


# ---------------------------------------------------------------------------
# Tests: _check_records
# ---------------------------------------------------------------------------


class TestCheckRecords:
    @pytest.mark.asyncio
    async def test_detects_new_record(self, async_db_session: AsyncSession) -> None:
        """_check_records creates a milestone event when ATH is detected."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source, MetricKeys.CLONES)
        project = await seed_project_for_collector(async_db_session)

        # Seed a daily metric that should trigger a record
        project_kwargs = {"project_id": project.id} if project is not None else {}
        metric = InsightMetric(
            date=datetime(2026, 4, 10),
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=999.0,
            period=Periods.DAILY,
            **project_kwargs,
        )
        async_db_session.add(metric)
        await async_db_session.flush()

        service = CollectorService(async_db_session, **collector_kwargs(project))
        broken = await service._check_records(SourceKeys.GITHUB_TRAFFIC)

        assert len(broken) > 0
        assert "999" in broken[0]

    @pytest.mark.asyncio
    async def test_no_record_when_lower(self, async_db_session: AsyncSession) -> None:
        """_check_records does not create event when value <= existing record."""
        from app.services.insights.models import InsightEvent

        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source, MetricKeys.CLONES)
        project = await seed_project_for_collector(async_db_session)
        project_kwargs = {"project_id": project.id} if project is not None else {}

        # Seed an existing milestone
        event = InsightEvent(
            date=datetime(2026, 4, 1),
            event_type="milestone_github",
            description="1,000 (GitHub 1-Day Clones)",
            metadata_={"category": "daily_clones"},
            **project_kwargs,
        )
        async_db_session.add(event)
        await async_db_session.flush()

        # Seed a daily metric lower than existing record
        metric = InsightMetric(
            date=datetime(2026, 4, 10),
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=500.0,
            period=Periods.DAILY,
            **project_kwargs,
        )
        async_db_session.add(metric)
        await async_db_session.flush()

        service = CollectorService(async_db_session, **collector_kwargs(project))
        broken = await service._check_records(SourceKeys.GITHUB_TRAFFIC)

        # Should not detect record for clones (500 < 1000)
        clone_records = [b for b in broken if "1-Day Clones" in b]
        assert len(clone_records) == 0

    @pytest.mark.asyncio
    async def test_no_records_for_untracked_source(
        self, async_db_session: AsyncSession
    ) -> None:
        """Sources without record checks return empty list."""
        service = CollectorService(async_db_session)
        broken = await service._check_records(SourceKeys.REDDIT)
        assert broken == []

    # Star daily/monthly record detection was removed from
    # CollectorService._check_records; the surface relied on a separate
    # ``new_star``-event aggregation path that the current collector
    # pipeline doesn't wire up. If that surface returns, restore the
    # ``test_star_daily_record`` and ``test_star_monthly_record`` cases
    # from git history.


# ---------------------------------------------------------------------------
# Tests: get_registered_sources
# ---------------------------------------------------------------------------


class TestGetRegisteredSources:
    def test_returns_all_registered(self) -> None:
        """Sources match what was wired up in COLLECTOR_REGISTRY at generation.

        Which collectors are present depends on the user's ``insights_*``
        copier flags (github/pypi default true, plausible/reddit default
        false), so we re-derive expected from the registry rather than
        hard-coding all 6 — that would fail any default-config init.
        """
        from app.services.insights.adapters.collectors.collection import COLLECTOR_REGISTRY

        service = CollectorService(AsyncMock())
        sources = service.get_registered_sources()

        assert sorted(sources) == sorted(COLLECTOR_REGISTRY.keys())
        assert sources, "At least one collector should be registered"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_collector_cls(success: bool = True) -> type:
    """Create a mock collector class that returns a fixed result."""

    class MockCollector:
        # Accepts an optional ``project=`` kwarg so it stays compatible with
        # CollectorService's instantiation contract in both auth=on
        # (collector_cls(db, project=...)) and auth=off (collector_cls(db)).
        def __init__(self, db: AsyncSession, **kwargs: object) -> None:
            self.db = db
            self.project = kwargs.get("project")

        @property
        def source_key(self) -> str:
            return "mock"

        async def collect(self, **kwargs: object) -> CollectionResult:
            return CollectionResult(
                source_key=self.source_key,
                success=success,
                rows_written=5 if success else 0,
            )

    return MockCollector
