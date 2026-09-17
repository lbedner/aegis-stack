"""
Constants for the insights service.

Single source of truth for source keys, metric type keys, and period values.
"""


class SourceKeys:
    """Insight source identifiers. Must match seed data in insight_source table."""

    GITHUB_TRAFFIC = "github_traffic"
    GITHUB_STARS = "github_stars"
    GITHUB_EVENTS = "github_events"
    PYPI = "pypi"
    PLAUSIBLE = "plausible"
    REDDIT = "reddit"

    ALL = [GITHUB_TRAFFIC, GITHUB_STARS, GITHUB_EVENTS, PYPI, PLAUSIBLE, REDDIT]


class MetricKeys:
    """Metric type identifiers. Must match seed data in insight_metric_type table."""

    # github_traffic
    CLONES = "clones"
    UNIQUE_CLONERS = "unique_cloners"
    VIEWS = "views"
    UNIQUE_VISITORS = "unique_visitors"
    REFERRERS = "referrers"
    POPULAR_PATHS = "popular_paths"
    # 14-day rolling totals — GitHub computes these server-side and returns
    # them as top-level `count` / `uniques` on /traffic/clones and /traffic/views.
    # Stored as one row per day (period=daily) so the rolling window itself
    # becomes a chartable time series. The `*_unique` variants are GitHub's
    # real distinct counts across the window, NOT sums of per-day uniques
    # (which double-count repeat users).
    CLONES_14D = "clones_14d"
    CLONES_14D_UNIQUE = "clones_14d_unique"
    VIEWS_14D = "views_14d"
    VIEWS_14D_UNIQUE = "views_14d_unique"

    # github_stars
    NEW_STAR = "new_star"

    # pypi
    DOWNLOADS_TOTAL = "downloads_total"
    DOWNLOADS_DAILY = "downloads_daily"
    DOWNLOADS_DAILY_HUMAN = "downloads_daily_human"
    DOWNLOADS_BY_COUNTRY = "downloads_by_country"
    DOWNLOADS_BY_INSTALLER = "downloads_by_installer"
    DOWNLOADS_BY_VERSION = "downloads_by_version"
    DOWNLOADS_BY_TYPE = "downloads_by_type"

    # github_events
    FORKS = "forks"
    RELEASES = "releases"
    STAR_EVENTS = "star_events"
    ACTIVITY_SUMMARY = "activity_summary"

    # plausible
    VISITORS = "visitors"
    PAGEVIEWS = "pageviews"
    AVG_DURATION = "avg_duration"
    BOUNCE_RATE = "bounce_rate"
    TOP_PAGES = "top_pages"
    TOP_COUNTRIES = "top_countries"
    TOP_SOURCES = "top_sources"

    # reddit
    POST_STATS = "post_stats"


class Periods:
    """Time period classifications for metric rows."""

    DAILY = "daily"
    CUMULATIVE = "cumulative"
    SNAPSHOT = "snapshot"
    EVENT = "event"


class Units:
    """Metric type units. Used in seed data and display formatting."""

    COUNT = "count"
    SECONDS = "seconds"
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    JSON = "json"


# Component name for health check registration
INSIGHT_COMPONENT_NAME = "insights"


def all_insights_key() -> str:
    """Cache key for the bulk ``/insights/all`` payload.

    Namespaced by ``BUILD_ID`` because a cached payload is only valid for
    the code that built it: change the shape of a response, or a threshold
    behind a computed field, and yesterday's entry is wrong even though
    the rows behind it never moved. A deploy moves the namespace, so new
    code starts clean and the orphans age out on their own TTL.

    Read at call time rather than bound at import so tests (and anything
    that reloads settings) see the current value.
    """
    from app.core.config import settings

    return f"insights:{settings.BUILD_ID}:all"


def project_insights_key(project_id: int) -> str:
    """Cache key for one project's bulk payload.

    Shared by the endpoint that writes it and the collector that clears
    it after a run, so the two cannot drift apart on the shape.
    """
    from app.core.config import settings

    return f"insights:{settings.BUILD_ID}:project:{project_id}:all"
