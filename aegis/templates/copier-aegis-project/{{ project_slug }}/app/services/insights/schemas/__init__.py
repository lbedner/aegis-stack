"""
Pydantic models for insight metadata shapes.

These define the structure of JSONB metadata stored in insight_metric rows.
Used for validation on write and typed access on read.

Usage:
    # Writing
    profile = StarProfileMetadata(username="ncthuc", ...)
    await upsert_metric(..., metadata=profile.model_dump())

    # Reading
    profile = StarProfileMetadata.model_validate(metric.metadata_)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# GitHub Traffic metadata
# ---------------------------------------------------------------------------


class ReferrerEntry(BaseModel):
    """Single referrer with view/unique counts."""

    views: int = Field(ge=0)
    uniques: int = Field(ge=0)


class PopularPathEntry(BaseModel):
    """Single popular path/page from GitHub traffic."""

    path: str
    title: str
    views: int = Field(ge=0)
    uniques: int = Field(ge=0)


class PopularPathsMetadata(BaseModel):
    """Metadata for the popular_paths metric type."""

    paths: list[PopularPathEntry] = Field(default_factory=list)


# Note: Referrer metadata is stored as dict[str, ReferrerEntry] directly,
# where keys are referrer domains. Use ReferrerEntry.model_validate() per entry.


# ---------------------------------------------------------------------------
# GitHub Stars metadata
# ---------------------------------------------------------------------------


class StarProfileMetadata(BaseModel):
    """GitHub user profile stored as metadata on a new_star event row."""

    username: str
    name: str | None = None
    location: str | None = None
    company: str | None = None
    bio: str | None = None
    email: str | None = None
    blog: str | None = None
    followers: int = Field(default=0, ge=0)
    following: int = Field(default=0, ge=0)
    public_repos: int = Field(default=0, ge=0)
    stars_given: int = Field(default=0, ge=0)
    account_created: str | None = None  # ISO 8601
    account_age_years: float | None = None
    github_pro: bool = False
    top_repo: str | None = None
    top_repo_stars: int | None = None


# ---------------------------------------------------------------------------
# PyPI metadata
# ---------------------------------------------------------------------------


class PyPIVersionDetail(BaseModel):
    """Per-version download breakdown."""

    total: int = 0
    human: int = 0


class PyPIDownloadMetadata(BaseModel):
    """Version breakdown metadata for daily PyPI downloads."""

    versions: dict[str, PyPIVersionDetail] = Field(default_factory=dict)


class PyPICountryBreakdown(BaseModel):
    """Country breakdown for PyPI downloads."""

    countries: dict[str, int] = Field(default_factory=dict)  # {"US": 1186, "CN": 206}


class PyPIInstallerBreakdown(BaseModel):
    """Installer breakdown for PyPI downloads."""

    installers: dict[str, int] = Field(
        default_factory=dict
    )  # {"bandersnatch": 1092, "pip": 39}


class PyPITypeBreakdown(BaseModel):
    """Distribution type breakdown for PyPI downloads."""

    types: dict[str, int] = Field(
        default_factory=dict
    )  # {"sdist": 1376, "bdist_wheel": 1032}


# ---------------------------------------------------------------------------
# Plausible metadata
# ---------------------------------------------------------------------------


class PlausibleSiteMetadata(BaseModel):
    """Site identifier on Plausible aggregate metric rows."""

    site: str


class PlausiblePageEntry(BaseModel):
    """Single page from Plausible analytics."""

    url: str
    visitors: int = Field(default=0, ge=0)
    pageviews: int = Field(default=0, ge=0)
    time_s: float | None = None  # Time on page in seconds
    scroll: float | None = None  # Scroll depth percentage (0-100)
    bounce_rate: float | None = None  # Per-page bounce rate (0-100)


class PlausibleTopPagesMetadata(BaseModel):
    """Metadata for the top_pages metric type."""

    site: str
    pages: list[PlausiblePageEntry] = Field(default_factory=list)


class PlausibleCountryEntry(BaseModel):
    """Single country from Plausible analytics."""

    country: str
    visitors: int = Field(default=0, ge=0)


class PlausibleTopCountriesMetadata(BaseModel):
    """Metadata for the top_countries metric type."""

    site: str
    countries: list[PlausibleCountryEntry] = Field(default_factory=list)


class PlausibleSourceEntry(BaseModel):
    """Single traffic source (Direct/None, Google, github.com, etc.)."""

    source: str
    visitors: int = Field(default=0, ge=0)


class PlausibleTopSourcesMetadata(BaseModel):
    """Metadata for the top_sources metric type — referrer breakdown
    from Plausible's `visit:source` property."""

    site: str
    sources: list[PlausibleSourceEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reddit metadata
# ---------------------------------------------------------------------------


class RedditPostMetadata(BaseModel):
    """Reddit post stats stored as metadata on a post_stats snapshot row."""

    post_id: str
    subreddit: str | None = None
    title: str | None = None
    comments: int = Field(default=0, ge=0)
    views: int | None = None
    shares: int | None = None
    upvote_ratio: float | None = None
    url: str | None = None


# ---------------------------------------------------------------------------
# Event metadata
# ---------------------------------------------------------------------------


class ReleaseEventMetadata(BaseModel):
    """Metadata for release-type events."""

    version: str
    url: str | None = None


class RedditPostEventMetadata(BaseModel):
    """Metadata for reddit_post-type events."""

    subreddit: str
    url: str | None = None
    post_id: str | None = None


class ExternalEventMetadata(BaseModel):
    """Metadata for external events (industry news, etc.)."""

    url: str | None = None
    source: str | None = None


# ---------------------------------------------------------------------------
# GitHub Events metadata (from ClickHouse)
# ---------------------------------------------------------------------------


class ForkEventMetadata(BaseModel):
    """Metadata for a fork event from ClickHouse GitHub data."""

    actor: str
    date: str  # ISO date


class ReleaseEventMetadata2(BaseModel):
    """Metadata for a release event from ClickHouse GitHub data."""

    tag: str
    name: str | None = None
    actor: str


class ActivitySummaryMetadata(BaseModel):
    """Daily event type counts from ClickHouse GitHub data."""

    push: int = 0
    issues: int = 0
    pull_requests: int = 0
    pull_request_reviews: int = 0
    issue_comments: int = 0
    forks: int = 0
    stars: int = 0
    releases: int = 0
    creates: int = 0
    deletes: int = 0


# ---------------------------------------------------------------------------
# API response models
# ---------------------------------------------------------------------------


class BulkInsightsResponse(BaseModel):
    """Full bulk response for /api/v1/insights/all.

    When constructed from JSON (via model_validate), date strings are
    coerced to datetime objects so downstream code can compare dates.
    """

    model_config = {"arbitrary_types_allowed": True}

    daily: dict[str, list[InsightMetric]]
    events: dict[str, list[InsightMetric]]
    insight_events: list[InsightEvent]
    sources: list[InsightSource]
    latest: dict[str, InsightMetric | None]

    def model_post_init(self, __context: Any) -> None:
        """Coerce date strings to datetime after construction from JSON."""
        from datetime import datetime as dt

        def _fix_date(obj: Any) -> None:
            if hasattr(obj, "date") and isinstance(obj.date, str):
                obj.date = dt.fromisoformat(obj.date)

        for rows in self.daily.values():
            for m in rows:
                _fix_date(m)
        for rows in self.events.values():
            for m in rows:
                _fix_date(m)
        for ev in self.insight_events:
            _fix_date(ev)
        for _key, m in self.latest.items():
            if m:
                _fix_date(m)


# Resolve forward references after models are defined
from app.services.insights.models import (  # noqa: E402, F401
    InsightEvent,
    InsightMetric,
    InsightSource,
)

BulkInsightsResponse.model_rebuild()
