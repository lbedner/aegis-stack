"""
Tests for InsightQueryService async query layer.
"""

from datetime import datetime, timedelta

import pytest
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import (
    InsightEvent,
    InsightMetric,
    InsightMetricType,
    InsightSource,
)
from app.services.insights.domains.metrics import (
    DAILY_KEYS,
    EVENT_KEYS,
    InsightQueryService,
)
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_source(
    session: AsyncSession, key: str = SourceKeys.GITHUB_TRAFFIC
) -> InsightSource:
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

    Centralizes the auth=on requirement that every metric/event row
    have a non-null ``project_id``: the per-test ``async_db_session``
    holds at most one Project across all helper calls.

    Returns ``None`` in auth=off builds (no Project model exists),
    which signals to the helpers below to skip the ``project_id``
    field entirely.
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
        email="query-service-test@example.com",
        full_name="Query Service Test",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    from tests._test_org import ensure_org_for_user

    org_id = await ensure_org_for_user(session, user)
    project = Project(
        slug="qsvc", name="qsvc",
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
    metadata: dict | None = None,
) -> InsightMetric:
    project = await _ensure_project(session)
    project_kwargs = {"project_id": project.id} if project is not None else {}
    metric = InsightMetric(
        date=date,
        metric_type_id=metric_type.id,  # type: ignore[arg-type]
        value=value,
        period=period,
        **project_kwargs,
    )
    if metadata:
        metric.metadata_ = metadata
    session.add(metric)
    await session.flush()
    return metric


async def _seed_event(
    session: AsyncSession,
    event_type: str,
    description: str,
    date: datetime | None = None,
    metadata: dict | None = None,
) -> InsightEvent:
    project = await _ensure_project(session)
    project_kwargs = {"project_id": project.id} if project is not None else {}
    event = InsightEvent(
        date=date or datetime.now(),
        event_type=event_type,
        description=description,
        **project_kwargs,
    )
    if metadata:
        event.metadata_ = metadata
    session.add(event)
    await session.flush()
    return event


# ---------------------------------------------------------------------------
# Tests: get_daily
# ---------------------------------------------------------------------------


class TestGetDaily:
    @pytest.mark.asyncio
    async def test_returns_rows_after_cutoff(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        now = datetime(2026, 4, 10)
        for i in range(5):
            await _seed_metric(
                async_db_session, mt, now - timedelta(days=i), float(10 + i)
            )

        qs = InsightQueryService(session=async_db_session)
        cutoff = now - timedelta(days=2)
        rows = await qs.get_daily(MetricKeys.CLONES, cutoff)

        assert len(rows) == 3
        assert all(r.date >= cutoff for r in rows)

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_key(
        self, async_db_session: AsyncSession
    ) -> None:
        qs = InsightQueryService(session=async_db_session)
        rows = await qs.get_daily("nonexistent_key", datetime(2020, 1, 1))
        assert rows == []

    @pytest.mark.asyncio
    async def test_ordering_is_ascending(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        dates = [datetime(2026, 4, d) for d in [3, 1, 5, 2, 4]]
        for d in dates:
            await _seed_metric(async_db_session, mt, d, 10.0)

        qs = InsightQueryService(session=async_db_session)
        rows = await qs.get_daily(MetricKeys.CLONES, datetime(2026, 4, 1))

        result_dates = [r.date for r in rows]
        assert result_dates == sorted(result_dates)


# ---------------------------------------------------------------------------
# Tests: get_daily_range
# ---------------------------------------------------------------------------


class TestGetDailyRange:
    @pytest.mark.asyncio
    async def test_includes_start_excludes_end(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        for day in range(1, 6):
            await _seed_metric(async_db_session, mt, datetime(2026, 4, day), float(day))

        qs = InsightQueryService(session=async_db_session)
        rows = await qs.get_daily_range(
            MetricKeys.CLONES, datetime(2026, 4, 2), datetime(2026, 4, 4)
        )

        dates = {r.date for r in rows}
        assert datetime(2026, 4, 2) in dates
        assert datetime(2026, 4, 3) in dates
        assert datetime(2026, 4, 4) not in dates

    @pytest.mark.asyncio
    async def test_empty_range(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 1), 10.0)

        qs = InsightQueryService(session=async_db_session)
        rows = await qs.get_daily_range(
            MetricKeys.CLONES, datetime(2026, 5, 1), datetime(2026, 5, 10)
        )
        assert rows == []


# ---------------------------------------------------------------------------
# Tests: get_latest
# ---------------------------------------------------------------------------


class TestGetLatest:
    @pytest.mark.asyncio
    async def test_returns_most_recent(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(async_db_session, mt, datetime(2026, 4, 1), 10.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 5), 50.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 3), 30.0)

        qs = InsightQueryService(session=async_db_session)
        latest = await qs.get_latest(MetricKeys.CLONES)

        assert latest is not None
        assert latest.value == 50.0
        assert latest.date == datetime(2026, 4, 5)

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(
        self, async_db_session: AsyncSession
    ) -> None:
        qs = InsightQueryService(session=async_db_session)
        assert await qs.get_latest("nonexistent") is None


# ---------------------------------------------------------------------------
# Tests: get_events / get_all_events / get_events_in_range
# ---------------------------------------------------------------------------


class TestGetEvents:
    @pytest.mark.asyncio
    async def test_returns_event_period_rows(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 10.0, Periods.DAILY
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 1.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 2), 2.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_events(MetricKeys.CLONES, datetime(2026, 4, 1))

        assert len(events) == 2
        assert all(e.period == Periods.EVENT for e in events)

    @pytest.mark.asyncio
    async def test_respects_cutoff(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 3, 1), 1.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 5), 2.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_events(MetricKeys.CLONES, datetime(2026, 4, 1))

        assert len(events) == 1
        assert events[0].date == datetime(2026, 4, 5)


class TestGetAllEvents:
    @pytest.mark.asyncio
    async def test_returns_all_regardless_of_date(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2020, 1, 1), 1.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 2.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_all_events(MetricKeys.CLONES)

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_ascending_order(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 5), 2.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 1.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_all_events(MetricKeys.CLONES)

        assert events[0].date < events[1].date


class TestGetEventsInRange:
    @pytest.mark.asyncio
    async def test_includes_start_excludes_end(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 1.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 3), 2.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 5), 3.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_events_in_range(
            MetricKeys.CLONES, datetime(2026, 4, 1), datetime(2026, 4, 5)
        )

        assert len(events) == 2
        dates = {e.date for e in events}
        assert datetime(2026, 4, 1) in dates
        assert datetime(2026, 4, 3) in dates
        assert datetime(2026, 4, 5) not in dates


# ---------------------------------------------------------------------------
# Tests: get_all_metrics
# ---------------------------------------------------------------------------


class TestGetAllMetrics:
    @pytest.mark.asyncio
    async def test_returns_all_periods(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 10.0, Periods.DAILY
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 1.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        metrics = await qs.get_all_metrics(MetricKeys.CLONES)

        assert len(metrics) == 2
        periods = {m.period for m in metrics}
        assert Periods.DAILY in periods
        assert Periods.EVENT in periods

    @pytest.mark.asyncio
    async def test_descending_order(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(async_db_session, mt, datetime(2026, 4, 1), 1.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 5), 5.0)

        qs = InsightQueryService(session=async_db_session)
        metrics = await qs.get_all_metrics(MetricKeys.CLONES)

        assert metrics[0].date > metrics[1].date


# ---------------------------------------------------------------------------
# Tests: sum_range / sum_daily
# ---------------------------------------------------------------------------


class TestSumRange:
    @pytest.mark.asyncio
    async def test_sums_values_in_range(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(async_db_session, mt, datetime(2026, 4, 1), 10.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 2), 20.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 3), 30.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 4), 40.0)

        qs = InsightQueryService(session=async_db_session)
        total = await qs.sum_range(
            MetricKeys.CLONES, datetime(2026, 4, 2), datetime(2026, 4, 4)
        )

        assert total == 50  # 20 + 30

    @pytest.mark.asyncio
    async def test_zero_for_empty_range(self, async_db_session: AsyncSession) -> None:
        qs = InsightQueryService(session=async_db_session)
        total = await qs.sum_range(
            "nonexistent", datetime(2026, 1, 1), datetime(2026, 1, 2)
        )
        assert total == 0


class TestSumDaily:
    @pytest.mark.asyncio
    async def test_sums_from_cutoff(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 3, 1), 100.0
        )  # before cutoff
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 1), 10.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 2), 20.0)
        await _seed_metric(async_db_session, mt, datetime(2026, 4, 3), 30.0)

        qs = InsightQueryService(session=async_db_session)
        total = await qs.sum_daily(MetricKeys.CLONES, datetime(2026, 4, 1))

        assert total == 60  # 10 + 20 + 30 (excludes 100)


# ---------------------------------------------------------------------------
# Tests: InsightEvent queries
# ---------------------------------------------------------------------------


class TestInsightEvents:
    @pytest.mark.asyncio
    async def test_returns_all_when_no_filters(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_event(async_db_session, "release", "v1.0", datetime(2026, 4, 1))
        await _seed_event(async_db_session, "star", "Star #50", datetime(2026, 4, 2))
        await _seed_event(
            async_db_session, "reddit_post", "NWN post", datetime(2026, 4, 3)
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_insight_events()

        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_filters_by_type(self, async_db_session: AsyncSession) -> None:
        await _seed_event(async_db_session, "release", "v1.0", datetime(2026, 4, 1))
        await _seed_event(async_db_session, "star", "Star #50", datetime(2026, 4, 2))
        await _seed_event(
            async_db_session, "reddit_post", "NWN post", datetime(2026, 4, 3)
        )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_insight_events(type_filter={"release", "star"})

        assert len(events) == 2
        types = {e.event_type for e in events}
        assert types == {"release", "star"}

    @pytest.mark.asyncio
    async def test_filters_by_cutoff(self, async_db_session: AsyncSession) -> None:
        await _seed_event(async_db_session, "release", "old", datetime(2026, 3, 1))
        await _seed_event(async_db_session, "release", "new", datetime(2026, 4, 5))

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_insight_events(cutoff=datetime(2026, 4, 1))

        assert len(events) == 1
        assert events[0].description == "new"

    @pytest.mark.asyncio
    async def test_combined_filters(self, async_db_session: AsyncSession) -> None:
        await _seed_event(
            async_db_session, "release", "old release", datetime(2026, 3, 1)
        )
        await _seed_event(
            async_db_session, "release", "new release", datetime(2026, 4, 5)
        )
        await _seed_event(async_db_session, "star", "new star", datetime(2026, 4, 5))

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_insight_events(
            cutoff=datetime(2026, 4, 1), type_filter={"release"}
        )

        assert len(events) == 1
        assert events[0].description == "new release"


class TestGetRecentInsightEvents:
    @pytest.mark.asyncio
    async def test_returns_limited_results(
        self, async_db_session: AsyncSession
    ) -> None:
        for i in range(20):
            await _seed_event(
                async_db_session,
                "star",
                f"Star #{i}",
                datetime(2026, 4, 1) + timedelta(hours=i),
            )

        qs = InsightQueryService(session=async_db_session)
        events = await qs.get_recent_insight_events(limit=5)

        assert len(events) == 5


class TestGetMilestoneEvents:
    @pytest.mark.asyncio
    async def test_returns_milestones_and_features(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_event(
            async_db_session,
            "milestone_github",
            "New ATH: 100 clones",
            datetime(2026, 4, 1),
        )
        await _seed_event(
            async_db_session,
            "milestone_pypi",
            "New ATH: 50 downloads",
            datetime(2026, 4, 2),
        )
        await _seed_event(
            async_db_session, "feature", "Added Mandarin CLI", datetime(2026, 4, 3)
        )
        await _seed_event(async_db_session, "release", "v0.6.9", datetime(2026, 4, 4))
        await _seed_event(async_db_session, "star", "Star #100", datetime(2026, 4, 5))

        qs = InsightQueryService(session=async_db_session)
        milestones = await qs.get_milestone_events()

        assert len(milestones) == 3
        types = {m.event_type for m in milestones}
        assert types == {"milestone_github", "milestone_pypi", "feature"}


# ---------------------------------------------------------------------------
# Tests: get_release_metrics / get_sources
# ---------------------------------------------------------------------------


class TestGetReleaseMetrics:
    @pytest.mark.asyncio
    async def test_returns_release_rows(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        releases_mt = await _seed_metric_type(async_db_session, source, "releases")
        other_mt = await _seed_metric_type(async_db_session, source, MetricKeys.CLONES)

        await _seed_metric(
            async_db_session,
            releases_mt,
            datetime(2026, 4, 1),
            1.0,
            metadata={"tag": "v0.6.9"},
        )
        await _seed_metric(async_db_session, other_mt, datetime(2026, 4, 1), 100.0)

        qs = InsightQueryService(session=async_db_session)
        releases = await qs.get_release_metrics()

        assert len(releases) == 1
        assert releases[0].metadata_.get("tag") == "v0.6.9"


class TestGetSources:
    @pytest.mark.asyncio
    async def test_returns_all_sources(self, async_db_session: AsyncSession) -> None:
        await _seed_source(async_db_session, SourceKeys.GITHUB_TRAFFIC)
        await _seed_source(async_db_session, SourceKeys.PYPI)

        qs = InsightQueryService(session=async_db_session)
        sources = await qs.get_sources()

        assert len(sources) == 2
        keys = {s.key for s in sources}
        assert SourceKeys.GITHUB_TRAFFIC in keys
        assert SourceKeys.PYPI in keys


# ---------------------------------------------------------------------------
# Tests: compute_cutoffs
# ---------------------------------------------------------------------------


class TestComputeCutoffs:
    def test_normal_days(self) -> None:
        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(14)

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        expected_cutoff = now - timedelta(days=14)
        expected_prev = expected_cutoff - timedelta(days=14)

        assert cutoff == expected_cutoff
        assert prev_cutoff == expected_prev

    def test_all_time(self) -> None:
        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(9999)

        assert cutoff == datetime(2000, 1, 1)
        assert prev_cutoff == datetime(2000, 1, 1)


# ---------------------------------------------------------------------------
# Tests: Type caching
# ---------------------------------------------------------------------------


class TestTypeCaching:
    @pytest.mark.asyncio
    async def test_caches_type_lookups(self, async_db_session: AsyncSession) -> None:
        source = await _seed_source(async_db_session)
        await _seed_metric_type(async_db_session, source)

        qs = InsightQueryService(session=async_db_session)

        # First call populates cache
        result1 = await qs._get_type(MetricKeys.CLONES)
        assert result1 is not None

        # Second call returns cached value
        result2 = await qs._get_type(MetricKeys.CLONES)
        assert result2 is result1  # Same object (from cache, not re-queried)

        # Cache stores None for missing keys too
        result3 = await qs._get_type("nonexistent")
        assert result3 is None
        assert "nonexistent" in qs._type_cache


# ---------------------------------------------------------------------------
# Tests: load_all
# ---------------------------------------------------------------------------


class TestLoadAll:
    @pytest.mark.asyncio
    async def test_daily_contains_seeded_data(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session)
        mt = await _seed_metric_type(async_db_session, source, MetricKeys.CLONES)

        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 10.0, Periods.DAILY
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 2), 20.0, Periods.DAILY
        )

        qs = InsightQueryService(session=async_db_session)
        bulk = await qs.load_all()

        assert len(bulk.daily["clones"]) == 2
        assert bulk.daily["clones"][0].value == 10.0

    @pytest.mark.asyncio
    async def test_events_contains_seeded_data(
        self, async_db_session: AsyncSession
    ) -> None:
        source = await _seed_source(async_db_session, SourceKeys.GITHUB_STARS)
        mt = await _seed_metric_type(async_db_session, source, "new_star")

        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 1), 1.0, Periods.EVENT
        )
        await _seed_metric(
            async_db_session, mt, datetime(2026, 4, 2), 2.0, Periods.EVENT
        )

        qs = InsightQueryService(session=async_db_session)
        bulk = await qs.load_all()

        assert len(bulk.events["new_star"]) == 2

    @pytest.mark.asyncio
    async def test_insight_events_loaded(self, async_db_session: AsyncSession) -> None:
        await _seed_event(async_db_session, "release", "v1.0", datetime(2026, 4, 1))
        await _seed_event(async_db_session, "star", "Star #50", datetime(2026, 4, 2))

        qs = InsightQueryService(session=async_db_session)
        bulk = await qs.load_all()

        assert len(bulk.insight_events) == 2

    @pytest.mark.asyncio
    async def test_sources_loaded(self, async_db_session: AsyncSession) -> None:
        await _seed_source(async_db_session, SourceKeys.GITHUB_TRAFFIC)
        await _seed_source(async_db_session, SourceKeys.PYPI)

        qs = InsightQueryService(session=async_db_session)
        bulk = await qs.load_all()

        assert len(bulk.sources) == 2

    @pytest.mark.asyncio
    async def test_empty_keys_return_empty_lists(
        self, async_db_session: AsyncSession
    ) -> None:
        """Keys with no data return empty lists, not missing keys."""
        qs = InsightQueryService(session=async_db_session)
        bulk = await qs.load_all()

        for key in DAILY_KEYS:
            assert key in bulk.daily
            assert bulk.daily[key] == []

        for key in EVENT_KEYS:
            assert key in bulk.events
            assert bulk.events[key] == []
