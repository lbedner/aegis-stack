"""
Goal metric catalog — display metadata + resolver for the `GoalMetric` enum.

Single source of truth for:
- What metrics the user can build goals against (values are pulled from the enum)
- How those user-facing keys map to the underlying (source_key, metric_type_key)
  tuple used to query `insight_metric` for progress computation.

The `/api/v1/insights/goals/metrics` endpoint serves this catalog to the
frontend as a JSON list so the goal-creation form can populate its dropdown.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.services.insights.constants import MetricKeys, SourceKeys, Units
from app.services.insights.models import GoalMetric


class AggregationStrategy(StrEnum):
    """How to turn `insight_metric` rows into a single scalar for progress.

    - SUM: add up the `value` column. Right for daily counters like clones,
           pageviews, downloads — each row is "N things happened that day".
    - COUNT: count the rows themselves. Right for event streams like
             `new_star` where each row represents one occurrence and `value`
             carries unrelated metadata (the star's sequence number).
    """

    SUM = "sum"
    COUNT = "count"


@dataclass(frozen=True)
class GoalMetricInfo:
    """Display + resolver metadata for a goal-trackable metric."""

    key: GoalMetric  # user-facing key (e.g., "github.stars")
    label: str  # display label (e.g., "GitHub Stars")
    source_label: str  # grouping label for the UI (e.g., "GitHub")
    unit: str  # count, percentage, etc. (from Units)
    source_key: str  # InsightSource.key — for querying
    metric_type_key: str  # InsightMetricType.key — for querying
    aggregation: AggregationStrategy = AggregationStrategy.SUM


# Ordered; the UI renders in this sequence and groups by source_label.
GOAL_METRIC_CATALOG: dict[GoalMetric, GoalMetricInfo] = {
    GoalMetric.GITHUB_STARS: GoalMetricInfo(
        key=GoalMetric.GITHUB_STARS,
        label="Stars",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_STARS,
        metric_type_key=MetricKeys.NEW_STAR,
        # Each row is one star event; `value` carries the star's sequence
        # number (not a count), so we count rows, not sum values.
        aggregation=AggregationStrategy.COUNT,
    ),
    GoalMetric.GITHUB_CLONES: GoalMetricInfo(
        key=GoalMetric.GITHUB_CLONES,
        label="Clones",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_TRAFFIC,
        metric_type_key=MetricKeys.CLONES,
    ),
    GoalMetric.GITHUB_UNIQUE_CLONERS: GoalMetricInfo(
        key=GoalMetric.GITHUB_UNIQUE_CLONERS,
        label="Unique cloners",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_TRAFFIC,
        metric_type_key=MetricKeys.UNIQUE_CLONERS,
    ),
    GoalMetric.GITHUB_VIEWS: GoalMetricInfo(
        key=GoalMetric.GITHUB_VIEWS,
        label="Repo views",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_TRAFFIC,
        metric_type_key=MetricKeys.VIEWS,
    ),
    GoalMetric.GITHUB_UNIQUE_VISITORS: GoalMetricInfo(
        key=GoalMetric.GITHUB_UNIQUE_VISITORS,
        label="Unique visitors",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_TRAFFIC,
        metric_type_key=MetricKeys.UNIQUE_VISITORS,
    ),
    GoalMetric.GITHUB_FORKS: GoalMetricInfo(
        key=GoalMetric.GITHUB_FORKS,
        label="Forks",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_EVENTS,
        metric_type_key=MetricKeys.FORKS,
    ),
    GoalMetric.GITHUB_RELEASES: GoalMetricInfo(
        key=GoalMetric.GITHUB_RELEASES,
        label="Releases",
        source_label="GitHub",
        unit=Units.COUNT,
        source_key=SourceKeys.GITHUB_EVENTS,
        metric_type_key=MetricKeys.RELEASES,
    ),
    GoalMetric.PYPI_DOWNLOADS: GoalMetricInfo(
        key=GoalMetric.PYPI_DOWNLOADS,
        label="Downloads",
        source_label="PyPI",
        unit=Units.COUNT,
        source_key=SourceKeys.PYPI,
        metric_type_key=MetricKeys.DOWNLOADS_DAILY,
    ),
    GoalMetric.DOCS_VISITORS: GoalMetricInfo(
        key=GoalMetric.DOCS_VISITORS,
        label="Visitors",
        source_label="Docs",
        unit=Units.COUNT,
        source_key=SourceKeys.PLAUSIBLE,
        metric_type_key=MetricKeys.VISITORS,
    ),
    GoalMetric.DOCS_PAGEVIEWS: GoalMetricInfo(
        key=GoalMetric.DOCS_PAGEVIEWS,
        label="Pageviews",
        source_label="Docs",
        unit=Units.COUNT,
        source_key=SourceKeys.PLAUSIBLE,
        metric_type_key=MetricKeys.PAGEVIEWS,
    ),
}


def get_metric_info(key: GoalMetric) -> GoalMetricInfo:
    """Resolve a user-facing goal metric to its display + query metadata."""
    return GOAL_METRIC_CATALOG[key]


def list_metrics() -> list[GoalMetricInfo]:
    """Catalog in display order for the goal-creation dropdown."""
    return list(GOAL_METRIC_CATALOG.values())
