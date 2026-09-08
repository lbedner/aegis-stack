"""The Overview tab: the hero rate, supporting cards, milestones and
the project card."""

from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.core.time import utcnow
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import (
    DailyTrafficPoint,
    MetricCardView,
    OverviewHero,
    OverviewView,
    ProjectInfoView,
)
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.events import (
    event_type_options,
    milestones,
    recent_events_ungrouped,
)
from app.services.insights.views.formatting import day_str, pct
from app.services.insights.views.stars import cumulative_stars


def build(bulk: BulkInsightsResponse, days: int = 14) -> OverviewView:
    """Hero metric is **average daily unique cloners** over the selected
    range, the editorial king metric. A rate, not a sum, so it stays
    interpretable across any range without the "are these deduplicated?"
    footgun of a raw 14d-unique total.
    """
    cutoff, prev_cutoff = range_cutoffs(days)

    clones_rows = [r for r in bulk.daily.get("clones", []) if r.date >= cutoff]
    unique_rows = [r for r in bulk.daily.get("unique_cloners", []) if r.date >= cutoff]
    views_rows = [r for r in bulk.daily.get("views", []) if r.date >= cutoff]
    visitors_rows = [
        r for r in bulk.daily.get("unique_visitors", []) if r.date >= cutoff
    ]

    # Daily series for the chart, same shape as the GitHub tab so the
    # chart renderer stays uniform.
    unique_map = {day_str(r.date): int(r.value) for r in unique_rows}
    views_map = {day_str(r.date): int(r.value) for r in views_rows}
    visitors_map = {day_str(r.date): int(r.value) for r in visitors_rows}
    daily: list[DailyTrafficPoint] = [
        DailyTrafficPoint(
            date=day_str(r.date),
            clones=int(r.value),
            unique_cloners=unique_map.get(day_str(r.date), 0),
            views=views_map.get(day_str(r.date), 0),
            unique_visitors=visitors_map.get(day_str(r.date), 0),
        )
        for r in clones_rows
    ]

    total_clones = sum(d.clones for d in daily)
    total_unique = sum(d.unique_cloners for d in daily)
    total_views = sum(d.views for d in daily)

    # Avg-daily metrics divide by the days we have data for, not the
    # requested range, so a mid-range collection start does not deflate them.
    observed_days = len(daily) or 1
    avg_unique = total_unique / observed_days
    avg_clones = total_clones / observed_days

    # Prior-period comparison for the hero card, symmetric window.
    prev_unique_rows = [
        r
        for r in bulk.daily.get("unique_cloners", [])
        if prev_cutoff <= r.date < cutoff
    ]
    prev_observed = len(prev_unique_rows) or 1
    prev_avg_unique = sum(r.value for r in prev_unique_rows) / prev_observed
    hero_change = pct(avg_unique, prev_avg_unique)

    prev_clones_total = sum(
        r.value for r in bulk.daily.get("clones", []) if prev_cutoff <= r.date < cutoff
    )
    prev_views_total = sum(
        r.value for r in bulk.daily.get("views", []) if prev_cutoff <= r.date < cutoff
    )

    star_events = bulk.events.get("new_star", [])

    # Last-day-delta labels for cards where "what happened yesterday"
    # is more interesting than the % change.
    def _last_day_label(key: str) -> str | None:
        rows = bulk.daily.get(key, [])
        if not rows:
            return None
        last = rows[-1]
        now = utcnow()
        try:
            dt = datetime.strptime(day_str(last.date), "%Y-%m-%d")
        except ValueError:
            return None
        days_ago = (now - dt).days
        val = int(last.value)
        prefix = f"+{val}" if val >= 0 else str(val)
        if days_ago == 0:
            return f"{prefix} today"
        if days_ago == 1:
            return f"{prefix} yesterday"
        return f"{prefix} {days_ago}d ago"

    # Stars label: last star event, e.g. "+1 8d ago"
    star_label = None
    if star_events:
        now = utcnow()
        try:
            dt = datetime.strptime(day_str(star_events[-1].date), "%Y-%m-%d")
            days_ago = (now - dt).days
            star_label = (
                "+1 today"
                if days_ago == 0
                else "+1 yesterday"
                if days_ago == 1
                else f"+1 {days_ago}d ago"
            )
        except ValueError:
            pass

    total_row = bulk.latest.get("downloads_total")
    visitors_docs_in_range = sum(
        int(r.value) for r in bulk.daily.get("visitors", []) if r.date >= cutoff
    )
    prev_visitors_docs = sum(
        int(r.value)
        for r in bulk.daily.get("visitors", [])
        if prev_cutoff <= r.date < cutoff
    )

    # Five supporting cards. Repo-side Views shows reach beyond clones;
    # Docs Visitors shows the documentation funnel. Pageviews and unique
    # visitors have their own tabs, keeping this row to one clean line.
    metrics = [
        MetricCardView(label="Stars", value=len(star_events), change_label=star_label),
        MetricCardView(
            label="PyPI Downloads",
            value=int(total_row.value) if total_row else 0,
            change_label=_last_day_label("downloads_daily"),
        ),
        MetricCardView(
            label="Clones",
            value=int(total_clones),
            change_pct=pct(total_clones, prev_clones_total),
            change_label=_last_day_label("clones"),
        ),
        MetricCardView(
            label="Repo Views",
            value=int(total_views),
            change_pct=pct(total_views, prev_views_total),
            change_label=_last_day_label("views"),
        ),
        MetricCardView(
            label="Docs Visitors",
            value=visitors_docs_in_range,
            change_pct=pct(visitors_docs_in_range, prev_visitors_docs),
        ),
    ]

    # Hero is None with zero cloner data, so the UI hides the card rather
    # than render an empty "0 / day" placeholder.
    hero: OverviewHero | None = None
    if unique_rows or clones_rows:
        hero = OverviewHero(
            avg_daily_unique_cloners=round(avg_unique, 1),
            range_days=days,
            change_pct=hero_change,
            total_unique_cloners=int(total_unique),
            total_clones=int(total_clones),
            avg_daily_clones=round(avg_clones, 1),
        )

    # The Recent Activity feed is decoupled from the metric window (the
    # cards already scope to ``days``) and deliberately un-grouped: a
    # timeline of what happened, not a daily summary.
    events = recent_events_ungrouped(bulk, days=90)
    return OverviewView(
        project=project_info(bulk),
        hero=hero,
        metrics=metrics,
        milestones=milestones(bulk),
        daily=daily,
        stars_daily=cumulative_stars(star_events, cutoff),
        events=events,
        event_types=event_type_options(events),
    )


def project_info(bulk: BulkInsightsResponse) -> ProjectInfoView | None:
    """The hero card model from settings plus live data.

    None when nothing is configured (no GitHub owner/repo AND no explicit
    project name), so the UI hides the card rather than render a shell.
    """
    owner = (settings.INSIGHT_GITHUB_OWNER or "").strip()
    repo = (settings.INSIGHT_GITHUB_REPO or "").strip()
    name = (settings.INSIGHT_PROJECT_NAME or "").strip() or repo
    if not name:
        return None

    github_repo_slug = f"{owner}/{repo}" if (owner and repo) else None
    github_url = f"https://github.com/{github_repo_slug}" if github_repo_slug else None

    pypi_package = (settings.INSIGHT_PYPI_PACKAGE or "").strip() or None
    pypi_url = f"https://pypi.org/project/{pypi_package}/" if pypi_package else None

    # Live counts read from each metric's native shape: stars/forks as
    # per-event rows, downloads as one cumulative snapshot, docs counters
    # as daily aggregates.

    # Stars: metric-event rows first, falling back to insight_events rows
    # with event_type='star' (data from an older collector version).
    stars = len(bulk.events.get("new_star", []))
    if stars == 0:
        stars = sum(1 for ev in bulk.insight_events if ev.event_type == "star")
    stars = stars or None

    fork_events = bulk.events.get("forks") or bulk.events.get("fork") or []
    forks = len(fork_events)
    if forks == 0:
        forks = sum(
            1 for ev in bulk.insight_events if ev.event_type in {"fork", "forks"}
        )
    forks = forks or None

    downloads_row = bulk.latest.get("downloads_total")
    downloads_total = int(downloads_row.value) if downloads_row else None

    pageviews = sum(int(r.value) for r in bulk.daily.get("pageviews", []))
    visitors = sum(int(r.value) for r in bulk.daily.get("visitors", []))

    return ProjectInfoView(
        name=name,
        description=(settings.INSIGHT_PROJECT_DESCRIPTION or "").strip(),
        github_url=github_url,
        github_repo=github_repo_slug,
        homepage_url=(settings.INSIGHT_PROJECT_HOMEPAGE or "").strip() or None,
        pypi_package=pypi_package,
        pypi_url=pypi_url,
        stars=stars,
        forks=forks,
        downloads_total=downloads_total,
        docs_pageviews=pageviews or None,
        docs_visitors=visitors or None,
    )
