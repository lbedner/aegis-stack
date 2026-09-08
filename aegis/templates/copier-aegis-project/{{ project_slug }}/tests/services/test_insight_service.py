"""
Tests for InsightService query layer and record detection.
"""

from datetime import datetime, timedelta

import pytest
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.service import InsightService
from app.services.insights.models import (
    InsightMetric,
    InsightMetricType,
    InsightSource,
)
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_source(
    session: AsyncSession, key: str = SourceKeys.GITHUB_TRAFFIC
) -> InsightSource:
    """Create a source row for testing."""
    source = InsightSource(
        key=key, display_name="Test Source", collection_interval_hours=6, enabled=True
    )
    session.add(source)
    await session.flush()
    return source


async def _seed_metric_type(
    session: AsyncSession,
    source: InsightSource,
    key: str = MetricKeys.CLONES,
    unit: str = "count",
) -> InsightMetricType:
    """Create a metric type row for testing."""
    mt = InsightMetricType(
        source_id=source.id,  # type: ignore[arg-type]
        key=key,
        display_name=key.replace("_", " ").title(),
        unit=unit,
    )
    session.add(mt)
    await session.flush()
    return mt


async def _ensure_project(session: AsyncSession) -> object | None:
    """Lazily create (or reuse) a Project for this test session.

    Returns ``None`` in auth=off builds (no Project model exists), so
    metrics can be inserted without ``project_id`` in single-tenant mode.
    """
    try:
        from app.models.user import User
        from app.services.insights.models import Project
    except ImportError:
        return None
    result = await session.exec(select(Project).limit(1))
    existing = result.first()
    if existing is not None:
        return existing
    user = User(
        email="insight-service-test@example.com",
        full_name="Insight Service Test",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    from tests._test_org import ensure_org_for_user

    org_id = await ensure_org_for_user(session, user)
    project = Project(
        slug="isvc", name="isvc",
        owner_user_id=user.id,  # type: ignore[arg-type]
        organization_id=org_id,
    )
    session.add(project)
    await session.flush()
    return project


async def _seed_metric(
    session: AsyncSession,
    metric_type: InsightMetricType,
    date: datetime,
    value: float,
    period: str = Periods.DAILY,
) -> InsightMetric:
    """Create a metric row for testing."""
    project = await _ensure_project(session)
    project_kwargs = {"project_id": project.id} if project is not None else {}
    metric = InsightMetric(
        date=date,
        metric_type_id=metric_type.id,  # type: ignore[arg-type]
        value=value,
        period=period,
        **project_kwargs,
    )
    session.add(metric)
    await session.flush()
    return metric


# ---------------------------------------------------------------------------
# Tests: Record Detection
# ---------------------------------------------------------------------------


class TestRecordDetection:
    """Test InsightService.check_and_update_records."""

    @pytest.mark.asyncio
    async def test_creates_first_record(self, async_db_session: AsyncSession) -> None:
        """First value for a metric creates a new record."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)
        service = InsightService(async_db_session)

        broken = await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=100.0,
            achieved_date=datetime(2026, 3, 20),
        )

        assert broken is True

        records = await service.get_records()
        assert len(records) == 1
        assert records[0].value == 100.0
        assert records[0].previous_value is None

    @pytest.mark.asyncio
    async def test_updates_when_exceeded(self, async_db_session: AsyncSession) -> None:
        """Higher value shifts current to previous and sets new record."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)
        service = InsightService(async_db_session)

        await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=100.0,
            achieved_date=datetime(2026, 3, 20),
        )

        broken = await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=200.0,
            achieved_date=datetime(2026, 3, 21),
        )

        assert broken is True

        records = await service.get_records()
        assert len(records) == 1
        assert records[0].value == 200.0
        assert records[0].previous_value == 100.0
        assert records[0].previous_date == datetime(2026, 3, 20)

    @pytest.mark.asyncio
    async def test_no_update_when_lower(self, async_db_session: AsyncSession) -> None:
        """Lower value does not update the record."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)
        service = InsightService(async_db_session)

        await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=100.0,
            achieved_date=datetime(2026, 3, 20),
        )

        broken = await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=50.0,
            achieved_date=datetime(2026, 3, 21),
        )

        assert broken is False

        records = await service.get_records()
        assert records[0].value == 100.0

    @pytest.mark.asyncio
    async def test_equal_value_no_update(self, async_db_session: AsyncSession) -> None:
        """Equal value does not break the record."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)
        service = InsightService(async_db_session)

        await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=100.0,
            achieved_date=datetime(2026, 3, 20),
        )

        broken = await service.check_and_update_records(
            metric_type_id=mt.id,  # type: ignore[arg-type]
            value=100.0,
            achieved_date=datetime(2026, 3, 21),
        )

        assert broken is False


# ---------------------------------------------------------------------------
# Tests: Rolling 14-Day Window
# ---------------------------------------------------------------------------


class TestRolling14d:
    """Test InsightService.get_rolling_14d."""

    @pytest.mark.asyncio
    async def test_sums_last_14_days(self, async_db_session: AsyncSession) -> None:
        """Sums daily values within the 14-day window."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(7):
            await _seed_metric(async_db_session, mt, now - timedelta(days=i), 10.0)

        service = InsightService(async_db_session)
        total = await service.get_rolling_14d(mt.id)  # type: ignore[arg-type]

        assert total == 70.0

    @pytest.mark.asyncio
    async def test_excludes_old_data(self, async_db_session: AsyncSession) -> None:
        """Data older than 14 days is not included."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # One row within window, one outside
        await _seed_metric(async_db_session, mt, now - timedelta(days=1), 50.0)
        await _seed_metric(async_db_session, mt, now - timedelta(days=20), 999.0)

        service = InsightService(async_db_session)
        total = await service.get_rolling_14d(mt.id)  # type: ignore[arg-type]

        assert total == 50.0

    @pytest.mark.asyncio
    async def test_empty_returns_zero(self, async_db_session: AsyncSession) -> None:
        """No data returns 0.0."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        service = InsightService(async_db_session)
        total = await service.get_rolling_14d(mt.id)  # type: ignore[arg-type]

        assert total == 0.0


# ---------------------------------------------------------------------------
# Tests: Events
# ---------------------------------------------------------------------------


class TestEvents:
    """Test InsightService event management."""

    @pytest.mark.asyncio
    async def test_add_event(self, async_db_session: AsyncSession) -> None:
        """Can create a contextual event."""
        project = await _ensure_project(async_db_session)
        service_kwargs = (
            {"project_id": project.id} if project is not None else {}  # type: ignore[union-attr]
        )
        service = InsightService(async_db_session, **service_kwargs)

        event = await service.add_event(
            event_type="release",
            description="Shipped v0.6.8 Auth/RBAC",
            metadata={"version": "0.6.8"},
        )

        assert event.id is not None
        assert event.event_type == "release"
        assert event.description == "Shipped v0.6.8 Auth/RBAC"

    @pytest.mark.asyncio
    async def test_get_events(self, async_db_session: AsyncSession) -> None:
        """Can retrieve events."""
        project = await _ensure_project(async_db_session)
        service_kwargs = (
            {"project_id": project.id} if project is not None else {}  # type: ignore[union-attr]
        )
        service = InsightService(async_db_session, **service_kwargs)

        await service.add_event("release", "v1")
        await service.add_event("reddit_post", "NWN post")

        events = await service.get_events()
        assert len(events) == 2


# ---------------------------------------------------------------------------
# Tests: Sources and Metric Types
# ---------------------------------------------------------------------------


class TestSourcesAndTypes:
    """Test source and metric type queries."""

    @pytest.mark.asyncio
    async def test_get_sources(self, async_db_session: AsyncSession) -> None:
        """Returns all sources."""
        await _seed_source(async_db_session, SourceKeys.GITHUB_TRAFFIC)
        await _seed_source(async_db_session, SourceKeys.PYPI)

        service = InsightService(async_db_session)
        sources = await service.get_sources()

        assert len(sources) == 2

    @pytest.mark.asyncio
    async def test_get_metric_types_filtered(
        self, async_db_session: AsyncSession
    ) -> None:
        """Returns metric types filtered by source."""
        source = await _seed_source(async_db_session)
        await _seed_metric_type(async_db_session, source, MetricKeys.CLONES)
        await _seed_metric_type(async_db_session, source, MetricKeys.VIEWS)

        other_source = await _seed_source(async_db_session, SourceKeys.PYPI)
        await _seed_metric_type(
            async_db_session, other_source, MetricKeys.DOWNLOADS_TOTAL
        )

        service = InsightService(async_db_session)
        types = await service.get_metric_types(source.id)

        assert len(types) == 2
        keys = {t.key for t in types}
        assert MetricKeys.CLONES in keys
        assert MetricKeys.VIEWS in keys


# ---------------------------------------------------------------------------
# Tests: Status Summary
# ---------------------------------------------------------------------------


class TestStatusSummary:
    """Test InsightService.get_status_summary."""

    @pytest.mark.asyncio
    async def test_summary_with_data(self, async_db_session: AsyncSession) -> None:
        """Summary includes sources, records, and total metrics."""
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)
        await _seed_metric(async_db_session, mt, datetime(2026, 3, 31), 345.0)

        service = InsightService(async_db_session)
        summary = await service.get_status_summary()

        assert summary["total_metrics"] == 1
        assert len(summary["sources"]) == 1
        assert summary["sources"][0]["key"] == SourceKeys.GITHUB_TRAFFIC

    @pytest.mark.asyncio
    async def test_summary_empty_db(self, async_db_session: AsyncSession) -> None:
        """Summary works with no data."""
        service = InsightService(async_db_session)
        summary = await service.get_status_summary()

        assert summary["total_metrics"] == 0
        assert summary["sources"] == []
        assert summary["records"] == []
