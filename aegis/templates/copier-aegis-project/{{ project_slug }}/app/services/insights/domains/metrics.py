"""The metrics domain: project-scoped reads over the time series.

``InsightQueryService`` is what the dashboard and API slice: point reads
per metric key, and ``load_all``, the six-query bulk load the views
render from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.insights import queries
from app.services.insights.constants import Periods
from app.services.insights.models import (
    InsightEvent,
    InsightMetric,
    InsightMetricType,
    InsightSource,
)
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.utils import day_start, range_cutoffs

# Metric keys grouped by query type
DAILY_KEYS = [
    "clones",
    "unique_cloners",
    "views",
    "unique_visitors",
    # GitHub's server-side 14-day rolling totals (one row per day).
    "clones_14d",
    "clones_14d_unique",
    "views_14d",
    "views_14d_unique",
    "star_events",
    "activity_summary",
    "downloads_daily",
    "downloads_daily_human",
    "downloads_by_installer",
    "downloads_by_country",
    "downloads_by_version",
    "downloads_by_type",
    "visitors",
    "pageviews",
    "avg_duration",
    "bounce_rate",
    "top_pages",
    "top_countries",
    "top_sources",
]
EVENT_KEYS = ["new_star", "forks", "releases", "post_stats"]
SNAPSHOT_KEYS = ["referrers", "popular_paths", "downloads_total"]


class InsightQueryService:
    """Async query service for insight metrics.

    When ``project_id`` is set, every metric / event SELECT is scoped to
    that project. When unset, no filter is applied (single-tenant
    fallback for builds without auth, or tooling that explicitly wants
    a global view). The two modes share one code path; the filter is
    a no-op when ``project_id`` is None.
    """

    def __init__(
        self,
        session: AsyncSession,
        project_id: int | None = None,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self._type_cache: dict[str, InsightMetricType | None] = {}

    async def __aenter__(self) -> InsightQueryService:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass  # Session lifecycle managed by caller (deps)

    # -- metric type lookup (cached) ------------------------------------------

    async def _get_type(self, key: str) -> InsightMetricType | None:
        if key not in self._type_cache:
            self._type_cache[key] = await queries.metric_type_by_key(self.session, key)
        return self._type_cache[key]

    # -- core queries ---------------------------------------------------------

    async def get_daily(self, key: str, cutoff: datetime) -> list[InsightMetric]:
        """Fetch daily metrics for a key from cutoff date onward."""
        mt = await self._get_type(key)
        if not mt:
            return []
        return await queries.metrics_where(
            self.session,
            [mt.id],
            period=Periods.DAILY,
            since=cutoff,
            project_id=self.project_id,
        )

    async def get_daily_range(
        self,
        key: str,
        start: datetime,
        end: datetime,
    ) -> list[InsightMetric]:
        """Fetch daily metrics between start (inclusive) and end (exclusive)."""
        mt = await self._get_type(key)
        if not mt:
            return []
        return await queries.metrics_where(
            self.session,
            [mt.id],
            period=Periods.DAILY,
            since=start,
            before=end,
            order=None,
            project_id=self.project_id,
        )

    async def get_latest(self, key: str) -> InsightMetric | None:
        """Fetch the most recent metric row for a key."""
        mt = await self._get_type(key)
        if not mt:
            return None
        rows = await queries.metrics_where(
            self.session,
            [mt.id],
            order="date_desc",
            limit=1,
            project_id=self.project_id,
        )
        return rows[0] if rows else None

    async def get_events(self, key: str, cutoff: datetime) -> list[InsightMetric]:
        """Fetch event-period metrics for a key from cutoff onward."""
        mt = await self._get_type(key)
        if not mt:
            return []
        return await queries.metrics_where(
            self.session,
            [mt.id],
            period=Periods.EVENT,
            since=cutoff,
            order="date_desc",
            project_id=self.project_id,
        )

    async def get_all_events(self, key: str) -> list[InsightMetric]:
        """Fetch all event-period metrics for a key (no date filter)."""
        mt = await self._get_type(key)
        if not mt:
            return []
        return await queries.metrics_where(
            self.session, [mt.id], period=Periods.EVENT, project_id=self.project_id
        )

    async def get_events_in_range(
        self,
        key: str,
        start: datetime,
        end: datetime,
    ) -> list[InsightMetric]:
        """Fetch event-period metrics between start (inclusive) and end (exclusive)."""
        mt = await self._get_type(key)
        if not mt:
            return []
        return await queries.metrics_where(
            self.session,
            [mt.id],
            period=Periods.EVENT,
            since=start,
            before=end,
            order=None,
            project_id=self.project_id,
        )

    async def get_all_metrics(self, key: str) -> list[InsightMetric]:
        """Fetch all metrics for a key (any period, ordered by date desc)."""
        mt = await self._get_type(key)
        if not mt:
            return []
        return await queries.metrics_where(
            self.session, [mt.id], order="date_desc", project_id=self.project_id
        )

    async def sum_range(self, key: str, start: datetime, end: datetime) -> int:
        """Sum daily metric values between start and end."""
        rows = await self.get_daily_range(key, start, end)
        return sum(int(r.value) for r in rows)

    async def sum_daily(self, key: str, cutoff: datetime) -> int:
        """Sum all daily metric values from cutoff onward."""
        rows = await self.get_daily(key, cutoff)
        return sum(int(r.value) for r in rows)

    # -- insight events -------------------------------------------------------

    async def get_insight_events(
        self,
        cutoff: datetime | None = None,
        type_filter: set[str] | None = None,
    ) -> list[InsightEvent]:
        """Fetch InsightEvent rows with optional date and type filters."""
        return await queries.events_where(
            self.session,
            event_types=type_filter or None,
            since=day_start(cutoff.date()) if cutoff else None,
            order="date_asc",
            project_id=self.project_id,
        )

    async def get_recent_insight_events(self, limit: int = 15) -> list[InsightEvent]:
        """Fetch most recent InsightEvent rows."""
        return await queries.events_where(
            self.session, order="date_desc", limit=limit, project_id=self.project_id
        )

    async def get_milestone_events(self) -> list[InsightEvent]:
        """Fetch all milestone and feature events."""
        return await queries.events_where(
            self.session,
            event_types=["milestone_github", "milestone_pypi", "feature"],
            order=None,
            project_id=self.project_id,
        )

    async def get_release_metrics(self) -> list[InsightMetric]:
        """Fetch release metric rows."""
        mt = await self._get_type("releases")
        if not mt:
            return []
        return await queries.metrics_where(
            self.session, [mt.id], order=None, project_id=self.project_id
        )

    # -- sources --------------------------------------------------------------

    async def get_sources(self) -> list[InsightSource]:
        """Fetch all insight sources."""
        return await queries.sources(self.session)

    # -- bulk loader ----------------------------------------------------------

    async def load_all(self) -> BulkInsightsResponse:
        """Bulk-load all insight data in the minimum number of queries.

        Previously this ran ~50 separate SELECTs (one per key to look up
        the metric_type, one per key to fetch its rows, plus `get_latest`
        for each snapshot). The fan-out was mechanical loop-iteration, not
        a data dependency — so we collapse it with `IN (...)` clauses:

            1. one SELECT for all metric_types we care about
            2. one SELECT for every daily metric across every daily key
            3. one SELECT for every event metric across every event key
            4. one SELECT for every snapshot metric; pick the latest per
               key in Python (portable across dialects, vs. DISTINCT ON)
            5. one SELECT for insight_events
            6. one SELECT for insight_sources

        Total: 6 round-trips regardless of how many keys the app tracks.
        """
        all_keys = DAILY_KEYS + EVENT_KEYS + SNAPSHOT_KEYS
        types_by_key = await queries.metric_types_by_keys(self.session, all_keys)
        # Warm the instance-level cache so subsequent `.get_daily()` / etc.
        # calls in this request skip the DB hit we just did.
        for k in all_keys:
            self._type_cache[k] = types_by_key.get(k)

        # Daily metrics — one query spanning every daily type.
        daily: dict[str, list[InsightMetric]] = {k: [] for k in DAILY_KEYS}
        daily_type_ids = [types_by_key[k].id for k in DAILY_KEYS if k in types_by_key]
        if daily_type_ids:
            rows = await queries.metrics_where(
                self.session,
                daily_type_ids,
                period=Periods.DAILY,
                project_id=self.project_id,
            )
            id_to_key = {types_by_key[k].id: k for k in DAILY_KEYS if k in types_by_key}
            for m in rows:
                daily[id_to_key[m.metric_type_id]].append(m)

        # Event metrics — one query.
        events: dict[str, list[InsightMetric]] = {k: [] for k in EVENT_KEYS}
        event_type_ids = [types_by_key[k].id for k in EVENT_KEYS if k in types_by_key]
        if event_type_ids:
            rows = await queries.metrics_where(
                self.session,
                event_type_ids,
                period=Periods.EVENT,
                project_id=self.project_id,
            )
            id_to_key = {types_by_key[k].id: k for k in EVENT_KEYS if k in types_by_key}
            for m in rows:
                events[id_to_key[m.metric_type_id]].append(m)

        # Snapshots — one query, desc by date, take the first row per key.
        latest: dict[str, InsightMetric | None] = dict.fromkeys(SNAPSHOT_KEYS)
        snapshot_type_ids = [
            types_by_key[k].id for k in SNAPSHOT_KEYS if k in types_by_key
        ]
        if snapshot_type_ids:
            rows = await queries.metrics_where(
                self.session,
                snapshot_type_ids,
                order="date_desc",
                project_id=self.project_id,
            )
            id_to_key = {
                types_by_key[k].id: k for k in SNAPSHOT_KEYS if k in types_by_key
            }
            for m in rows:
                key = id_to_key[m.metric_type_id]
                if latest[key] is None:  # first iteration per key == latest date
                    latest[key] = m

        insight_events = await queries.events_where(
            self.session, order="date_asc", project_id=self.project_id
        )
        sources = await queries.sources(self.session)

        return BulkInsightsResponse(
            daily=daily,
            events=events,
            insight_events=insight_events,
            sources=sources,
            latest=latest,
        )

    # -- convenience: date helpers --------------------------------------------

    @staticmethod
    def compute_cutoffs(days: int) -> tuple[datetime, datetime]:
        """(cutoff, prev_cutoff): see ``utils.range_cutoffs``."""
        return range_cutoffs(days)
