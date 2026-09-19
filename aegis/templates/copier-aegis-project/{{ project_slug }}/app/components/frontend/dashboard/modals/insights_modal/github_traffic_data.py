"""Turning the bulk payload into what the traffic tab shows."""

from __future__ import annotations  # noqa: I001

from typing import Any

from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.views import InsightViewService
from app.services.insights.views.events import (
    GITHUB_EVENT_TYPES,
)


def traffic_data(bulk: BulkInsightsResponse, days: int = 14) -> dict[str, Any]:
    """Load GitHub data from bulk pre-loaded data with date cutoff."""
    from app.services.insights.domains.metrics import InsightQueryService

    cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

    # Traffic daily
    clones_rows = [r for r in bulk.daily.get("clones", []) if r.date >= cutoff]
    unique_rows = [r for r in bulk.daily.get("unique_cloners", []) if r.date >= cutoff]
    views_rows = [r for r in bulk.daily.get("views", []) if r.date >= cutoff]
    visitors_rows = [
        r for r in bulk.daily.get("unique_visitors", []) if r.date >= cutoff
    ]

    unique_map = {str(r.date)[:10]: int(r.value) for r in unique_rows}
    views_map = {str(r.date)[:10]: int(r.value) for r in views_rows}
    visitors_map = {str(r.date)[:10]: int(r.value) for r in visitors_rows}

    daily: list[dict[str, Any]] = []
    for r in clones_rows:
        day = str(r.date)[:10]
        clones = int(r.value)
        unique = unique_map.get(day, 0)
        views = views_map.get(day, 0)
        visitors = visitors_map.get(day, 0)
        # Skip days with no activity to avoid dead space on chart
        if clones == 0 and unique == 0 and views == 0 and visitors == 0:
            continue
        daily.append(
            {
                "date": day,
                "clones": clones,
                "unique_cloners": unique,
                "views": views,
                "unique_visitors": visitors,
            }
        )

    # Referrers (latest snapshot)
    referrers_row = bulk.latest.get("referrers")
    referrers: list[dict[str, Any]] = []
    if referrers_row and referrers_row.metadata_:
        meta = referrers_row.metadata_
        if isinstance(meta, dict) and not meta.get("referrers"):
            for domain, counts in meta.items():
                if isinstance(counts, dict):
                    referrers.append(
                        {
                            "domain": domain,
                            "views": counts.get("views", 0),
                            "uniques": counts.get("uniques", 0),
                        }
                    )
        else:
            for ref in meta.get("referrers", []):
                referrers.append(
                    {
                        "domain": ref.get("referrer", ref.get("domain", "unknown")),
                        "views": ref.get("count", ref.get("views", 0)),
                        "uniques": ref.get("uniques", 0),
                    }
                )
        referrers.sort(key=lambda x: -x["views"])

    # Popular paths (latest snapshot)
    paths_row = bulk.latest.get("popular_paths")
    popular_paths: list[dict[str, Any]] = []
    if paths_row and paths_row.metadata_:
        for p in paths_row.metadata_.get(
            "paths", paths_row.metadata_.get("popular_paths", [])
        ):
            popular_paths.append(
                {
                    "path": p.get("path", "unknown"),
                    "title": p.get("title", ""),
                    "views": p.get("count", p.get("views", 0)),
                    "uniques": p.get("uniques", 0),
                }
            )

    # Fork events
    fork_rows = [r for r in bulk.events.get("forks", []) if r.date >= cutoff]
    forks: list[dict[str, str]] = []
    for r in fork_rows:
        meta = r.metadata_ or {}
        forks.append({"actor": meta.get("actor", "unknown"), "date": str(r.date)[:10]})

    # Star events daily
    star_rows = [r for r in bulk.daily.get("star_events", []) if r.date >= cutoff]
    star_events_daily: list[dict[str, Any]] = []
    for r in star_rows:
        star_events_daily.append({"date": str(r.date)[:10], "stars": int(r.value)})

    # Activity summary daily
    activity_rows = [
        r for r in bulk.daily.get("activity_summary", []) if r.date >= cutoff
    ]
    activity_summary: list[dict[str, Any]] = []
    for r in activity_rows:
        meta = r.metadata_ or {}
        entry: dict[str, Any] = {"date": str(r.date)[:10]}
        for field in (
            "push",
            "issues",
            "pull_requests",
            "pull_request_reviews",
            "issue_comments",
            "forks",
            "stars",
            "releases",
            "creates",
            "deletes",
        ):
            entry[field] = meta.get(field, 0)
        activity_summary.append(entry)

    # Build all_events list for chips
    all_events: list[tuple[str, str, str]] = []

    # Release events from metrics
    release_rows = [r for r in bulk.events.get("releases", []) if r.date >= cutoff]
    releases: dict[str, str] = {}
    for r in release_rows:
        meta = r.metadata_ or {}
        tag = meta.get("tag", "")
        day = str(r.date)[:10]
        if tag:
            all_events.append((day, tag, "release"))
            if day in releases:
                releases[day] += f"\n{tag}"
            else:
                releases[day] = tag

    # InsightEvent rows filtered to GitHub-relevant types
    cutoff_str = str(cutoff.date())
    for ev in [
        ev
        for ev in bulk.insight_events
        if str(ev.date)[:10] >= cutoff_str and ev.event_type in GITHUB_EVENT_TYPES
    ]:
        day = str(ev.date)[:10]
        all_events.append((day, ev.description[:60], ev.event_type))
        # Only add release-type events to the releases annotation map
        if ev.event_type == "release":
            if day in releases:
                releases[day] += f"\n{ev.description[:60]}"
            else:
                releases[day] = ev.description[:60]

    all_events.sort(key=lambda x: x[0])

    # Average unique cloners by day-of-week (Sun..Sat) — sourced from
    # views package so this stays consistent with whatever the rest of
    # the app shows. Empty list when there's no cloner data, so the
    # builder can hide the chart instead of rendering an empty axis.
    github_view = InsightViewService(bulk).github(days=days)
    weekday = github_view.unique_cloners_by_weekday

    return {
        "daily": daily,
        "referrers": referrers,
        "popular_paths": popular_paths,
        "forks": forks,
        "releases": releases,
        "all_events": all_events,
        "activity_summary": activity_summary,
        "star_events_daily": star_events_daily,
        "weekday": weekday,
        "prev_clones": sum(
            int(r.value)
            for r in bulk.daily.get("clones", [])
            if prev_cutoff <= r.date < cutoff
        ),
        "prev_unique": sum(
            int(r.value)
            for r in bulk.daily.get("unique_cloners", [])
            if prev_cutoff <= r.date < cutoff
        ),
        "prev_views": sum(
            int(r.value)
            for r in bulk.daily.get("views", [])
            if prev_cutoff <= r.date < cutoff
        ),
        "prev_visitors": sum(
            int(r.value)
            for r in bulk.daily.get("unique_visitors", [])
            if prev_cutoff <= r.date < cutoff
        ),
    }
