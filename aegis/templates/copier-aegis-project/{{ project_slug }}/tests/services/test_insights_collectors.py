"""
Tests for insight collectors — BaseCollector helpers and GitHubTrafficCollector.
"""

from datetime import datetime

import pytest
from app.services.insights.adapters.collectors.base import CollectionResult

from ._collector_fixtures import collector_kwargs, seed_project_for_collector
from app.services.insights.constants import MetricKeys, Periods, SourceKeys
from app.services.insights.models import (
    InsightMetric,
    InsightMetricType,
    InsightSource,
)
from app.services.insights.schemas import ReferrerEntry
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_github_traffic(
    session: AsyncSession,
) -> tuple[InsightSource, dict[str, InsightMetricType]]:
    """Seed github_traffic source with all metric types."""
    source = InsightSource(
        key=SourceKeys.GITHUB_TRAFFIC,
        display_name="GitHub Traffic",
        collection_interval_hours=6,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    metric_types: dict[str, InsightMetricType] = {}
    for key in [
        MetricKeys.CLONES,
        MetricKeys.UNIQUE_CLONERS,
        MetricKeys.VIEWS,
        MetricKeys.UNIQUE_VISITORS,
        MetricKeys.REFERRERS,
        MetricKeys.POPULAR_PATHS,
        # GitHub server-computed 14-day rolling totals — collector writes these
        # alongside the per-day metrics, so they must exist for collect() to
        # succeed.
        MetricKeys.CLONES_14D,
        MetricKeys.CLONES_14D_UNIQUE,
        MetricKeys.VIEWS_14D,
        MetricKeys.VIEWS_14D_UNIQUE,
    ]:
        mt = InsightMetricType(
            source_id=source.id,  # type: ignore[arg-type]
            key=key,
            display_name=key.replace("_", " ").title(),
            unit="count"
            if key not in (MetricKeys.REFERRERS, MetricKeys.POPULAR_PATHS)
            else "json",
        )
        session.add(mt)
        await session.flush()
        metric_types[key] = mt

    return source, metric_types


# ---------------------------------------------------------------------------
# Tests: CollectionResult (Pydantic validation)
# ---------------------------------------------------------------------------


class TestCollectionResult:
    """Test CollectionResult Pydantic model."""

    def test_default_values(self) -> None:
        """Default values are correct."""
        result = CollectionResult(source_key="test", success=True)
        assert result.rows_written == 0
        assert result.rows_skipped == 0
        assert result.records_broken == []
        assert result.error is None

    def test_validation_rejects_negative_counts(self) -> None:
        """Negative row counts are rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CollectionResult(source_key="test", success=True, rows_written=-1)

    def test_serialization(self) -> None:
        """Can serialize to dict for API responses."""
        result = CollectionResult(
            source_key="github_traffic",
            success=True,
            rows_written=10,
            rows_skipped=4,
        )
        data = result.model_dump()
        assert data["source_key"] == "github_traffic"
        assert data["rows_written"] == 10


# ---------------------------------------------------------------------------
# Tests: BaseCollector.upsert_metric
# ---------------------------------------------------------------------------


class TestUpsertMetric:
    """Test BaseCollector.upsert_metric deduplication logic."""

    @pytest.mark.asyncio
    async def test_creates_new_row(self, async_db_session: AsyncSession) -> None:
        """First upsert creates a new metric row."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session)
        mt = metric_types[MetricKeys.CLONES]

        # Need a concrete collector to test base methods
        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        metric, created = await collector.upsert_metric(
            metric_type=mt,
            date=datetime(2026, 3, 31),
            value=345.0,
            period=Periods.DAILY,
        )

        assert created is True
        assert metric.value == 345.0

    @pytest.mark.asyncio
    async def test_updates_existing_row(self, async_db_session: AsyncSession) -> None:
        """Second upsert for same (type, date, period) updates instead of creating."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session)
        mt = metric_types[MetricKeys.CLONES]

        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        # First insert
        _, created1 = await collector.upsert_metric(
            metric_type=mt,
            date=datetime(2026, 3, 31),
            value=345.0,
            period=Periods.DAILY,
        )
        assert created1 is True

        # Second insert — same type + date + period
        metric, created2 = await collector.upsert_metric(
            metric_type=mt,
            date=datetime(2026, 3, 31),
            value=400.0,
            period=Periods.DAILY,
        )
        assert created2 is False
        assert metric.value == 400.0

        # Verify only one row exists
        result = await async_db_session.exec(
            select(InsightMetric).where(InsightMetric.metric_type_id == mt.id)
        )
        assert len(result.all()) == 1

    @pytest.mark.asyncio
    async def test_event_period_always_creates(
        self, async_db_session: AsyncSession
    ) -> None:
        """Event period rows are always new (no deduplication)."""
        _, metric_types = await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session)
        mt = metric_types[MetricKeys.CLONES]

        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        _, created1 = await collector.upsert_metric(
            metric_type=mt,
            date=datetime(2026, 3, 31),
            value=99.0,
            period=Periods.EVENT,
            metadata={"username": "star1"},
        )
        _, created2 = await collector.upsert_metric(
            metric_type=mt,
            date=datetime(2026, 3, 31),
            value=100.0,
            period=Periods.EVENT,
            metadata={"username": "star2"},
        )

        assert created1 is True
        assert created2 is True

        result = await async_db_session.exec(
            select(InsightMetric).where(
                InsightMetric.metric_type_id == mt.id,
                InsightMetric.period == Periods.EVENT,
            )
        )
        assert len(result.all()) == 2


# ---------------------------------------------------------------------------
# Tests: BaseCollector helpers
# ---------------------------------------------------------------------------


class TestBaseCollectorHelpers:
    """Test get_source and get_metric_type."""

    @pytest.mark.asyncio
    async def test_get_source(self, async_db_session: AsyncSession) -> None:
        """get_source returns the correct source row."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        source = await collector.get_source()

        assert source.key == SourceKeys.GITHUB_TRAFFIC

    @pytest.mark.asyncio
    async def test_get_source_missing_raises(
        self, async_db_session: AsyncSession
    ) -> None:
        """get_source raises RuntimeError when source not seeded."""
        project = await seed_project_for_collector(async_db_session)
        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with pytest.raises(RuntimeError, match="not found"):
            await collector.get_source()

    @pytest.mark.asyncio
    async def test_get_metric_type(self, async_db_session: AsyncSession) -> None:
        """get_metric_type returns the correct type row."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))
        mt = await collector.get_metric_type(MetricKeys.CLONES)

        assert mt.key == MetricKeys.CLONES
        assert mt.unit == "count"

    @pytest.mark.asyncio
    async def test_get_metric_type_missing_raises(
        self, async_db_session: AsyncSession
    ) -> None:
        """get_metric_type raises RuntimeError for unknown key."""
        await _seed_github_traffic(async_db_session)
        project = await seed_project_for_collector(async_db_session)

        from app.services.insights.adapters.collectors.github_traffic import (
            GitHubTrafficCollector,
        )

        collector = GitHubTrafficCollector(async_db_session, **collector_kwargs(project))

        with pytest.raises(RuntimeError, match="not found"):
            await collector.get_metric_type("nonexistent_metric")


# ---------------------------------------------------------------------------
# Tests: Pydantic Schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    """Test that Pydantic metadata schemas validate correctly."""

    def test_referrer_entry(self) -> None:
        """ReferrerEntry validates and serializes."""
        entry = ReferrerEntry(views=54, uniques=9)
        assert entry.views == 54
        data = entry.model_dump()
        assert data == {"views": 54, "uniques": 9}

    def test_referrer_entry_rejects_negative(self) -> None:
        """ReferrerEntry rejects negative values."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ReferrerEntry(views=-1, uniques=0)

    def test_star_profile_metadata(self) -> None:
        """StarProfileMetadata handles full and partial profiles."""
        from app.services.insights.schemas import StarProfileMetadata

        # Full profile
        full = StarProfileMetadata(
            username="ncthuc",
            name="Thuc Nguyen",
            location="Hanoi, Vietnam",
            company="teko.vn",
            followers=6,
            stars_given=50,
            account_age_years=15.0,
        )
        assert full.username == "ncthuc"

        # Minimal profile
        minimal = StarProfileMetadata(username="anonymous")
        assert minimal.followers == 0
        assert minimal.location is None

    def test_reddit_post_metadata(self) -> None:
        """RedditPostMetadata validates post stats."""
        from app.services.insights.schemas import RedditPostMetadata

        post = RedditPostMetadata(
            post_id="nwn_vault_revival",
            subreddit="neverwinternights",
            comments=20,
            views=17000,
            upvote_ratio=0.996,
        )
        assert post.post_id == "nwn_vault_revival"
        data = post.model_dump()
        assert data["views"] == 17000
