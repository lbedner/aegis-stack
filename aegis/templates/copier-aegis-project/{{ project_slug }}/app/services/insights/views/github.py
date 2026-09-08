"""The GitHub tab: traffic, referrers, popular paths, activity, weekday shape."""

from __future__ import annotations

from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import (
    ActivityDay,
    DailyTrafficPoint,
    GitHubView,
    MetricCardView,
    TrafficItem,
)
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.events import (
    GITHUB_EVENT_TYPES,
    event_type_options,
    filter_events,
)
from app.services.insights.views.formatting import day_str, pct, referrer_url


def repo_referrers(bulk: BulkInsightsResponse) -> list[TrafficItem]:
    """The GitHub repo referrer snapshot as TrafficItem rows, busiest first.
    Two snapshot shapes exist: a domain-keyed dict, and a ``referrers``
    list; both are read."""
    referrers: list[TrafficItem] = []
    row = bulk.latest.get("referrers")
    if not row or not row.metadata_:
        return referrers
    meta = row.metadata_
    if isinstance(meta, dict) and not meta.get("referrers"):
        for domain, counts in meta.items():
            if isinstance(counts, dict):
                referrers.append(
                    TrafficItem(
                        name=domain,
                        views=counts.get("views", 0),
                        uniques=counts.get("uniques", 0),
                        url=referrer_url(domain),
                    )
                )
    else:
        for ref in meta.get("referrers", []):
            name = ref.get("referrer", ref.get("domain", "unknown"))
            referrers.append(
                TrafficItem(
                    name=name,
                    views=ref.get("count", ref.get("views", 0)),
                    uniques=ref.get("uniques", 0),
                    url=referrer_url(name),
                )
            )
    referrers.sort(key=lambda x: -x.views)
    return referrers


def build(bulk: BulkInsightsResponse, days: int = 14) -> GitHubView:
    cutoff, prev_cutoff = range_cutoffs(days)

    clones_rows = [r for r in bulk.daily.get("clones", []) if r.date >= cutoff]
    unique_rows = [r for r in bulk.daily.get("unique_cloners", []) if r.date >= cutoff]
    views_rows = [r for r in bulk.daily.get("views", []) if r.date >= cutoff]
    visitors_rows = [
        r for r in bulk.daily.get("unique_visitors", []) if r.date >= cutoff
    ]

    unique_map = {day_str(r.date): int(r.value) for r in unique_rows}
    views_map = {day_str(r.date): int(r.value) for r in views_rows}
    visitors_map = {day_str(r.date): int(r.value) for r in visitors_rows}

    daily: list[DailyTrafficPoint] = []
    for r in clones_rows:
        day = day_str(r.date)
        daily.append(
            DailyTrafficPoint(
                date=day,
                clones=int(r.value),
                unique_cloners=unique_map.get(day, 0),
                views=views_map.get(day, 0),
                unique_visitors=visitors_map.get(day, 0),
            )
        )

    total_clones = sum(d.clones for d in daily)
    total_unique = sum(d.unique_cloners for d in daily)
    total_views = sum(d.views for d in daily)
    total_visitors = sum(d.unique_visitors for d in daily)

    def _prev(key: str) -> float:
        return sum(
            r.value for r in bulk.daily.get(key, []) if prev_cutoff <= r.date < cutoff
        )

    prev_clones = _prev("clones")
    prev_unique = _prev("unique_cloners")
    prev_views = _prev("views")
    prev_visitors = _prev("unique_visitors")

    # Forks and releases are event-keyed (each row is one fork/release), not daily counts.
    forks_total = sum(1 for r in bulk.events.get("forks", []) if r.date >= cutoff)
    releases_total = sum(1 for r in bulk.events.get("releases", []) if r.date >= cutoff)
    prev_forks = sum(
        1 for r in bulk.events.get("forks", []) if prev_cutoff <= r.date < cutoff
    )
    prev_releases = sum(
        1 for r in bulk.events.get("releases", []) if prev_cutoff <= r.date < cutoff
    )

    clone_ratio = f"{total_clones / total_unique:.1f}:1" if total_unique > 0 else "—"

    metrics = [
        MetricCardView(
            label="Clones",
            value=total_clones,
            change_pct=pct(total_clones, prev_clones),
        ),
        MetricCardView(
            label="Unique",
            value=total_unique,
            change_pct=pct(total_unique, prev_unique),
        ),
        MetricCardView(
            label="Views", value=total_views, change_pct=pct(total_views, prev_views)
        ),
        MetricCardView(
            label="Visitors",
            value=total_visitors,
            change_pct=pct(total_visitors, prev_visitors),
        ),
        MetricCardView(label="Clone Ratio", value=clone_ratio),
        MetricCardView(
            label="Forks", value=forks_total, change_pct=pct(forks_total, prev_forks)
        ),
        MetricCardView(
            label="Releases",
            value=releases_total,
            change_pct=pct(releases_total, prev_releases),
        ),
    ]

    # Popular paths (latest snapshot)
    popular_paths: list[TrafficItem] = []
    paths_row = bulk.latest.get("popular_paths")
    if paths_row and paths_row.metadata_:
        for p in paths_row.metadata_.get(
            "paths", paths_row.metadata_.get("popular_paths", [])
        ):
            popular_paths.append(
                TrafficItem(
                    name=p.get("path", "unknown"),
                    views=p.get("count", p.get("views", 0)),
                    uniques=p.get("uniques", 0),
                )
            )
        popular_paths.sort(key=lambda x: -x.views)

    # Activity summary, bucketed into 5 categories
    activity: list[ActivityDay] = []
    for r in (r for r in bulk.daily.get("activity_summary", []) if r.date >= cutoff):
        meta = r.metadata_ if hasattr(r, "metadata_") else {}
        if not isinstance(meta, dict):
            meta = {}
        activity.append(
            ActivityDay(
                date=day_str(r.date),
                code=sum(meta.get(f, 0) for f in ("push", "creates", "deletes")),
                issues=sum(meta.get(f, 0) for f in ("issues", "issue_comments")),
                prs=sum(
                    meta.get(f, 0) for f in ("pull_requests", "pull_request_reviews")
                ),
                community=sum(meta.get(f, 0) for f in ("forks", "stars")),
                releases=meta.get("releases", 0),
            )
        )

    # Average unique cloners by day of week, Sun..Sat. weekday() is
    # Mon=0..Sun=6; (w+1)%7 reorders Sun-first so the client indexes
    # straight into a labels array. Days without a metric row are absent
    # (not zero-filled), so the average covers observed days only. Empty
    # with no cloner data at all, so the client can tell "no data" from
    # "all zeroes".
    unique_cloners_by_weekday: list[float]
    if not unique_rows:
        unique_cloners_by_weekday = []
    else:
        weekday_sums: list[int] = [0] * 7
        weekday_counts: list[int] = [0] * 7
        for r in unique_rows:
            idx = (r.date.weekday() + 1) % 7
            weekday_sums[idx] += int(r.value)
            weekday_counts[idx] += 1
        unique_cloners_by_weekday = [
            (weekday_sums[i] / weekday_counts[i]) if weekday_counts[i] else 0.0
            for i in range(7)
        ]

    events = filter_events(bulk, GITHUB_EVENT_TYPES, cutoff=cutoff, days=days)
    return GitHubView(
        metrics=metrics,
        daily=daily,
        events=events,
        event_types=event_type_options(events),
        referrers=repo_referrers(bulk),
        popular_paths=popular_paths,
        activity=activity,
        unique_cloners_by_weekday=unique_cloners_by_weekday,
    )
