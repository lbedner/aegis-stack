"""The Stars tab, and the cumulative star series the Overview shares."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.time import utcnow
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import (
    BreakdownItem,
    DailyValuePoint,
    MetricCardView,
    StargazerView,
    StarsView,
)
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.events import all_events, event_type_options
from app.services.insights.views.formatting import day_str, short_date


def cumulative_stars(star_events: list[Any], cutoff: datetime) -> list[DailyValuePoint]:
    """One point per calendar day from the first star to today, carrying
    the running total forward on quiet days: a smooth monotonic curve
    (star-history style) rather than per-event spikes. Only days on or
    after ``cutoff`` are emitted."""
    daily: list[DailyValuePoint] = []
    if not star_events:
        return daily
    sorted_events = sorted(star_events, key=lambda r: r.date)
    per_day: dict[str, int] = {}
    for r in sorted_events:
        day = day_str(r.date)
        per_day[day] = per_day.get(day, 0) + 1
    start = datetime.strptime(day_str(sorted_events[0].date), "%Y-%m-%d")
    end = utcnow()
    running = 0
    cursor = start
    while cursor.date() <= end.date():
        day = cursor.strftime("%Y-%m-%d")
        running += per_day.get(day, 0)
        if cursor >= cutoff:
            daily.append(DailyValuePoint(date=day, value=running))
        cursor += timedelta(days=1)
    return daily


def build(bulk: BulkInsightsResponse, days: int = 14) -> StarsView:
    star_events = bulk.events.get("new_star", [])
    cutoff, _ = range_cutoffs(days)

    # Recent stargazer profiles from metadata
    recent_stars: list[StargazerView] = []
    for r in reversed(star_events[-20:]):
        meta = r.metadata_ if hasattr(r, "metadata_") else {}
        if isinstance(meta, dict) and meta.get("username"):
            recent_stars.append(
                StargazerView(
                    username=meta.get("username") or "",
                    location=meta.get("location") or "",
                    company=meta.get("company") or "",
                    followers=meta.get("followers") or 0,
                    date=short_date(r.date),
                )
            )

    # Country aggregation from star locations
    country_counts: dict[str, int] = {}
    for r in star_events:
        meta = r.metadata_ if hasattr(r, "metadata_") else {}
        loc = meta.get("location", "") if isinstance(meta, dict) else ""
        if loc:
            country_counts[loc] = country_counts.get(loc, 0) + 1
    top_countries = [
        BreakdownItem(name=k, value=v)
        for k, v in sorted(country_counts.items(), key=lambda x: -x[1])[:10]
    ]

    total = len(star_events)
    now = utcnow()
    last_30 = len([r for r in star_events if r.date >= now - timedelta(days=30)])
    last_7 = len([r for r in star_events if r.date >= now - timedelta(days=7)])

    metrics = [
        MetricCardView(label="Total Stars", value=total),
        MetricCardView(label="Last 30 Days", value=last_30),
        MetricCardView(label="Last 7 Days", value=last_7),
    ]

    events = all_events(bulk, days=days)
    return StarsView(
        metrics=metrics,
        daily=cumulative_stars(star_events, cutoff),
        recent_stars=recent_stars,
        top_countries=top_countries,
        events=events,
        event_types=event_type_options(events),
    )
