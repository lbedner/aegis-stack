"""The activity timeline: which events a tab shows, range-dependent
bucketing, and the milestone cards."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from app.services.insights.models import event_type_display
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import (
    ActivityEventView,
    EventTypeOption,
    MilestoneView,
)
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.formatting import (
    MILESTONE_COLORS,
    day_str,
    event_color,
    extract_max_number,
    pretty_date,
    short_date,
)

GITHUB_EVENT_TYPES = {
    "release",
    "fork",
    "star",
    "feature",
    "milestone_github",
    "anomaly_github",
    "localization",
    "external",
}
PYPI_EVENT_TYPES = {
    "release",
    "reddit_post",
    "star",
    "feature",
    "milestone_pypi",
    "localization",
    "external",
}
DOCS_EVENT_TYPES = {
    "release",
    "feature",
    "milestone_plausible",
    "localization",
    "external",
}

GroupedEvent = tuple[str, str, str, set[str]]


def group_events(events: list[tuple[str, str, str]], days: int) -> list[GroupedEvent]:
    """Group same-type events by time bucket for cleaner display.

    Args:
        events: (date_yyyy_mm_dd, label, event_type) tuples
        days: visible range in days

    Returns:
        (display_date, label, event_type, dates_set) tuples, newest first
    """
    if days <= 30 or not events:
        rows = [(date, label, etype, {date}) for date, label, etype in events]
        rows.sort(key=lambda x: x[0], reverse=True)
        return rows

    if days <= 90:

        def bucket_key(date_str: str) -> str:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
    else:

        def bucket_key(date_str: str) -> str:
            return date_str[:7]  # YYYY-MM

    buckets: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for date, label, etype in events:
        key = (bucket_key(date), etype)
        buckets.setdefault(key, []).append((date, label))

    result: list[GroupedEvent] = []
    for (_, etype), items in buckets.items():
        dates = {d for d, _ in items}
        first_date = min(dates)

        if len(items) == 1:
            result.append((items[0][0], items[0][1], etype, dates))
            continue

        if etype == "release":
            tags = [lbl for _, lbl in sorted(items)]
            label = f"{tags[0]}–{tags[-1]}" if len(tags) > 1 else tags[0]
        elif etype == "star":
            nums: list[int] = []
            for _, lbl in items:
                for m in re.findall(r"#(\d+)", lbl):
                    nums.append(int(m))
            if nums:
                label = f"⭐ #{min(nums)}-#{max(nums)} ({len(items)} events)"
            else:
                label = f"⭐ ({len(items)} stars)"
        elif etype == "reddit_post" or etype.startswith("milestone_"):
            # Keep these individual: each carries unique info (a reddit
            # post title, a milestone value like "804 clones") that a
            # "(N)" collapse would lose.
            for date, lbl in items:
                result.append((date, lbl, etype, {date}))
            continue
        else:
            label = f"{etype} ({len(items)})"

        result.append((first_date, label, etype, dates))

    result.sort(key=lambda x: x[0], reverse=True)
    return result


def raw_events(
    bulk: BulkInsightsResponse,
    type_set: set[str] | None,
    cutoff: datetime | None = None,
) -> list[tuple[str, str, str]]:
    """(date, label, event_type) tuples from insight_events plus release metrics."""
    results: list[tuple[str, str, str]] = []

    for e in bulk.insight_events:
        if type_set is not None and e.event_type not in type_set:
            continue
        if cutoff is not None and e.date < cutoff:
            continue
        results.append((day_str(e.date), e.description, e.event_type))

    include_releases = type_set is None or "release" in type_set
    if include_releases:
        for r in bulk.events.get("releases", []):
            if cutoff is not None and r.date < cutoff:
                continue
            meta = r.metadata_ if hasattr(r, "metadata_") else {}
            tag = meta.get("tag", "") if isinstance(meta, dict) else ""
            if tag:
                results.append((day_str(r.date), tag, "release"))

    return results


def event_type_options(events: list[ActivityEventView]) -> list[EventTypeOption]:
    """Distinct event types across a view's events, with friendly labels.

    Drives the filter chip menu. Computed from the view's own events, not
    the full bulk, so each page gets only the types that appear there.
    """
    seen: set[str] = set()
    out: list[EventTypeOption] = []
    for ev in events:
        if ev.event_type in seen:
            continue
        seen.add(ev.event_type)
        out.append(
            EventTypeOption(key=ev.event_type, label=event_type_display(ev.event_type))
        )
    out.sort(key=lambda o: o.label.lower())
    return out


def to_activity_events(grouped: list[GroupedEvent]) -> list[ActivityEventView]:
    return [
        ActivityEventView(
            event_type=etype,
            description=label,
            date=short_date(date),
            date_keys=sorted(d[5:] for d in dates),
            color=event_color(etype),
        )
        for date, label, etype, dates in grouped
    ]


def filter_events(
    bulk: BulkInsightsResponse,
    type_set: set[str],
    cutoff: datetime | None = None,
    days: int = 14,
) -> list[ActivityEventView]:
    """A tab's events, bucketed by range."""
    return to_activity_events(group_events(raw_events(bulk, type_set, cutoff), days))


def all_events(bulk: BulkInsightsResponse, days: int = 14) -> list[ActivityEventView]:
    """Every event in range, newest first, bucketed by range. ``days``
    drives BOTH the cutoff and the bucket width."""
    cutoff, _ = range_cutoffs(days)
    return to_activity_events(group_events(raw_events(bulk, None, cutoff), days))


def recent_events_ungrouped(
    bulk: BulkInsightsResponse, days: int = 90
) -> list[ActivityEventView]:
    """Raw sequential events for the Overview feed: a timeline of what
    happened, so two issues closed on one day stay two rows."""
    cutoff, _ = range_cutoffs(days)
    raw = raw_events(bulk, None, cutoff)
    raw.sort(key=lambda t: t[0], reverse=True)
    return [
        ActivityEventView(
            event_type=etype,
            description=label,
            date=short_date(date),
            date_keys=[date[5:]],
            color=event_color(etype),
        )
        for date, label, etype in raw
    ]


def milestones(bulk: BulkInsightsResponse) -> list[MilestoneView]:
    """Milestone cards: the best value per category, newest first."""
    best_per_category: dict[str, dict[str, Any]] = {}

    for ev in bulk.insight_events:
        if ev.event_type not in ("milestone_github", "milestone_pypi", "feature"):
            continue

        meta = ev.metadata_ if isinstance(ev.metadata_, dict) else {}
        category = meta.get("category", ev.description)

        hero_str = (
            extract_max_number(ev.description) if ev.event_type != "feature" else ""
        )
        value = int(hero_str.replace(",", "")) if hero_str else 0

        existing = best_per_category.get(category)
        if existing is None or value > existing.get("_value", 0):
            best_per_category[category] = {
                "date": ev.date,
                "description": ev.description,
                "event_type": ev.event_type,
                "category": category,
                "hero_str": hero_str,
                "_value": value,
            }

    ordered = sorted(best_per_category.values(), key=lambda m: m["date"], reverse=True)

    result: list[MilestoneView] = []
    for m in ordered:
        label = (
            m["category"].replace("_", " ").title()
            if m["category"] != m["description"]
            else m["description"][:30]
        )
        # Feature events show the description as the value; milestones the number
        if m["event_type"] == "feature":
            display_value = m["description"]
        else:
            display_value = m["hero_str"] or "—"

        result.append(
            MilestoneView(
                label=label,
                value=display_value,
                date=pretty_date(m["date"]),
                color=MILESTONE_COLORS.get(m["event_type"], "primary"),
                event_type=m["event_type"],
            )
        )

    return result
