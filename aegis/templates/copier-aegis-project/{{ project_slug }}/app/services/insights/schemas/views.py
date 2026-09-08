"""Pydantic models for insight view responses.

These are the display-ready shapes returned by the ``views`` package
and served by the /api/v1/insights/view/* endpoints.
"""

from pydantic import BaseModel, Field


class MetricCardView(BaseModel):
    """A single metric card with optional change percentage."""

    label: str
    value: int | float | str
    change_pct: int | None = None
    change_label: str | None = None
    lower_is_better: bool = False  # if true, negative change_pct is rendered as "good"


class MilestoneView(BaseModel):
    """A milestone/record card."""

    label: str
    value: str  # Formatted string, e.g. "804" or "Traefik + Deploy shipped"
    date: str  # Human-readable, e.g. "March 20, 2026"
    color: str  # DaisyUI/Flet color key: success, accent, secondary, etc.
    event_type: str


class ActivityEventView(BaseModel):
    """An activity feed event (possibly a grouped bucket of events)."""

    event_type: str
    description: str
    date: str  # Formatted, e.g. "Apr 03"
    date_keys: list[str] = Field(
        default_factory=list
    )  # MM-DD list for chart tooltip + chip selection
    color: str  # DaisyUI color key


class EventTypeOption(BaseModel):
    """One selectable event-type filter shown in the chip menu.

    Derived server-side from the events present in the view so the frontend
    never renders a dead chip. Keep in sync with `EVENT_TYPE_LABELS` in
    models.py for label strings."""

    key: str
    label: str


class DailyTrafficPoint(BaseModel):
    """A single day of GitHub traffic data."""

    date: str
    clones: int
    unique_cloners: int
    views: int
    unique_visitors: int


class DailyValuePoint(BaseModel):
    """A single day with one value (downloads, visitors, etc.)."""

    date: str
    value: int


class StargazerView(BaseModel):
    """A stargazer profile summary."""

    username: str
    location: str = ""
    company: str = ""
    followers: int = 0
    date: str = ""  # Formatted, e.g. "Apr 03"


class BreakdownItem(BaseModel):
    """A name/value pair for ranked lists (countries, versions, etc.)."""

    name: str
    value: int
    code: str = ""  # optional raw identifier (e.g. ISO-2 country code)
    url: str = ""  # optional click-through target (Top Pages -> live docs URL)


class DocsPageStats(BaseModel):
    """Per-page Plausible engagement stats for the Docs tab's Top Pages
    table. Richer than `BreakdownItem` — we keep the two apart so callers
    that just need name/value aren't forced through the wide shape.

    Bounce rate and scroll depth are Plausible percentages (0–100); time
    is seconds. Any of the engagement fields may be None when Plausible
    didn't report them (e.g., sites without engagement events enabled
    return no scroll_depth)."""

    path: str
    url: str = ""  # absolute click-through (https://<site><path>)
    visitors: int = 0
    pageviews: int = 0
    bounce_rate: float | None = None
    time_s: float | None = None
    scroll: float | None = None


class TrafficItem(BaseModel):
    """A name with views/uniques pair (referrers, popular paths)."""

    name: str
    views: int
    uniques: int
    url: str = ""  # optional click-through (referrer domain or popular-path URL)


class ActivityDay(BaseModel):
    """One day of activity summary, bucketed into categories."""

    date: str
    code: int = 0
    issues: int = 0
    prs: int = 0
    community: int = 0
    releases: int = 0


class RedditCountrySlice(BaseModel):
    code: str
    name: str
    pct: float


class RedditTopComment(BaseModel):
    author: str
    votes: int = 0
    text: str = ""


class RedditPostView(BaseModel):
    """An enriched Reddit post — mirrors what reddit.py collector stores on
    the `post_stats` metric's metadata. Rich fields (countries, hourly
    time-series, top comments) are optional; when absent, the expandable
    detail panel just hides them."""

    description: str  # "r/subreddit — title" (legacy display)
    title: str = ""  # raw post title
    date: str
    subreddit: str = ""
    upvotes: int = 0
    comments: int = 0
    upvote_ratio: float | None = None  # 0.0–1.0; ratio of upvotes to total votes
    views: int | None = None  # Reddit exposes this inconsistently
    shares: int | None = None
    url: str = ""  # original Reddit post URL for click-through
    # Rich metadata (optional; populated only for posts we've enriched):
    top_countries: list[RedditCountrySlice] = Field(default_factory=list)
    hourly_views_48h: list[int] = Field(default_factory=list)
    peak_hour: int | None = None  # argmax(hourly_views_48h) + 1, derived server-side
    top_comments: list[RedditTopComment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level view responses (one per tab)
# ---------------------------------------------------------------------------


class ProjectInfoView(BaseModel):
    """Static-ish display metadata for the "what is this?" hero card.

    Sourced from settings (INSIGHT_PROJECT_*, INSIGHT_GITHUB_*, INSIGHT_PYPI_*).
    Rendered prominently at the top of the Overview page so first-time
    viewers immediately know what project they're looking at.
    """

    name: str  # display name (falls back to github repo)
    description: str  # one-line tagline
    github_url: str | None = None  # link to the repo
    github_repo: str | None = None  # "owner/repo" slug for display
    homepage_url: str | None = None  # e.g. docs site
    pypi_package: str | None = None
    pypi_url: str | None = None
    stars: int | None = None  # pulled from insights data, not settings
    forks: int | None = None
    downloads_total: int | None = None
    # Docs stats — cumulative pageviews + unique visitors, if Plausible data
    # is present. Sourced from `bulk.daily` (plausible counters don't emit
    # per-star/per-event rows, just daily counts).
    docs_pageviews: int | None = None
    docs_visitors: int | None = None


class OverviewHero(BaseModel):
    """The headline metric on the overview page.

    Avg daily unique cloners is the editorial "king metric" — one number
    that captures whether the project is being picked up. Carries the
    range it was computed over so the page can label it correctly when
    the user changes the date picker.
    """

    avg_daily_unique_cloners: float  # sum(daily uniques) / N days
    range_days: int  # the N — drives the "over last N days" label
    change_pct: int | None = None  # vs prior equal-length window
    total_unique_cloners: int = 0  # sum of daily uniques across the range
    total_clones: int = 0  # sum of daily clones across the range
    avg_daily_clones: float = 0.0


class OverviewView(BaseModel):
    """Overview tab response."""

    project: ProjectInfoView | None = None
    hero: OverviewHero | None = None  # null when there's no cloner data yet
    metrics: list[MetricCardView]
    milestones: list[MilestoneView]
    daily: list[DailyTrafficPoint] = Field(default_factory=list)  # for the trend chart
    stars_daily: list[DailyValuePoint] = Field(
        default_factory=list
    )  # cumulative — star-history style
    events: list[ActivityEventView]
    event_types: list[EventTypeOption] = Field(default_factory=list)


class GitHubView(BaseModel):
    """GitHub tab response."""

    metrics: list[MetricCardView]
    daily: list[DailyTrafficPoint]
    events: list[ActivityEventView]
    event_types: list[EventTypeOption] = Field(default_factory=list)
    referrers: list[TrafficItem]
    popular_paths: list[TrafficItem]
    activity: list[ActivityDay]
    # Averaged over the selected range, ordered Sun..Sat (7 entries).
    # Empty when there's no cloner data in the range.
    unique_cloners_by_weekday: list[float] = Field(default_factory=list)


class StarsView(BaseModel):
    """Stars tab response."""

    metrics: list[MetricCardView]
    daily: list[DailyValuePoint]
    recent_stars: list[StargazerView]
    top_countries: list[BreakdownItem]
    events: list[ActivityEventView] = Field(default_factory=list)
    event_types: list[EventTypeOption] = Field(default_factory=list)


class VersionSeries(BaseModel):
    """One version's daily download totals, aligned to a shared date axis."""

    version: str
    values: list[int]


class PyPIView(BaseModel):
    """PyPI tab response."""

    metrics: list[MetricCardView]
    daily: list[DailyValuePoint]
    daily_human: list[DailyValuePoint]
    countries: list[BreakdownItem]  # full tail (up to 50) — map fidelity
    top_countries: list[BreakdownItem] = Field(
        default_factory=list
    )  # top 10 for the side table
    installers: list[BreakdownItem] = Field(default_factory=list)
    dist_types: list[BreakdownItem] = Field(default_factory=list)
    versions: list[BreakdownItem]
    version_totals: list[
        BreakdownItem
    ] = []  # every version, semver asc — for bar chart
    version_series: list[VersionSeries] = Field(default_factory=list)
    version_dates: list[str] = Field(default_factory=list)  # shared x-axis (YYYY-MM-DD)
    events: list[ActivityEventView]
    event_types: list[EventTypeOption] = Field(default_factory=list)


class SpotlightCard(BaseModel):
    """A spotlight card — either a big value with sublabel, or a ranked list."""

    label: str  # e.g. "Most Read", "Top Countries"
    value: str = ""  # big headline text (ignored if `items` is set)
    sublabel: str = ""  # small muted text under the value
    tooltip: str = ""  # hover text (e.g., full URL)
    items: list[BreakdownItem] = Field(
        default_factory=list
    )  # ranked list mode — shows #1, #2, #3 rows


class DocsView(BaseModel):
    """Docs/Plausible tab response."""

    metrics: list[MetricCardView]
    visitors: list[DailyValuePoint]
    pageviews: list[DailyValuePoint]
    top_pages: list[DocsPageStats]
    top_countries: list[BreakdownItem]
    countries: list[BreakdownItem] = Field(
        default_factory=list
    )  # full tail (with ISO codes) for the world map
    top_sources: list[
        BreakdownItem
    ] = []  # referrer breakdown (Direct/None, Google, github.com, ...)
    spotlights: list[SpotlightCard] = Field(default_factory=list)
    events: list[ActivityEventView] = Field(default_factory=list)
    event_types: list[EventTypeOption] = Field(default_factory=list)


class RedditView(BaseModel):
    """Reddit tab response."""

    total: int
    posts: list[RedditPostView]
