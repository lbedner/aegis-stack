"""Turning the bulk payload into what the PyPI tab shows."""

from __future__ import annotations  # noqa: I001

from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.views.events import (
    PYPI_EVENT_TYPES,
)


def version_sort_key(version: str) -> tuple[int, ...]:
    """Order versions roughly by release, for the downloads chart.

    Pre-release markers become separators, so 1.2.0rc1 reads as
    (1, 2, 0, 1). That puts it AFTER 1.2.0 rather than before it, which
    is backwards for a release candidate - the shorter tuple always
    wins. Behaviour preserved from when this was a nested function;
    worth fixing, but it reorders bars in a chart, so not quietly.

    Anything that is not a number sorts as zero rather than raising: a
    version string is whatever the index was given.
    """
    parts = version.replace("rc", ".").replace("a", ".").replace("b", ".").split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def split_downloads(info: dict | int) -> tuple[int, int, int]:
    """Total, human and bot counts for one version.

    Older rows carry a bare total rather than a breakdown, so an int
    means "all total, no attribution known" rather than zero humans.
    """
    if isinstance(info, dict):
        total, human = info.get("total", 0), info.get("human", 0)
    else:
        total, human = info, 0
    return total, human, total - human


def bot_share_label(total: int, bot: int) -> str:
    """Bot share as a percentage, or an em-dash when there is nothing
    to take a share of."""
    if total <= 0:
        return "\u2014"
    return f"{bot / total * 100:.0f}%"


def pypi_data(bulk: BulkInsightsResponse, days: int = 14) -> dict:
    """Load PyPI data from bulk pre-loaded data."""
    from app.services.insights.domains.metrics import InsightQueryService

    cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

    # Total
    total_row = bulk.latest.get("downloads_total")
    total = int(total_row.value) if total_row else 0

    # Daily total + human
    daily_rows = [r for r in bulk.daily.get("downloads_daily", []) if r.date >= cutoff]
    human_rows = [
        r for r in bulk.daily.get("downloads_daily_human", []) if r.date >= cutoff
    ]
    human_map = {str(r.date)[:10]: int(r.value) for r in human_rows}

    daily = []
    for r in daily_rows:
        day = str(r.date)[:10]
        t = int(r.value)
        h = human_map.get(day, 0)
        daily.append({"date": day, "total": t, "human": h})

    today_total = daily[-1]["total"] if daily else 0
    today_human = daily[-1]["human"] if daily else 0

    # Bot % computed over entire selected range
    range_total = sum(d["total"] for d in daily)
    range_human = sum(d["human"] for d in daily)
    bot_pct = (
        ((range_total - range_human) / range_total * 100) if range_total > 0 else 0
    )

    # Latest installer breakdown (aggregate from all days)
    all_installers: dict[str, int] = {}
    for r in [
        r for r in bulk.daily.get("downloads_by_installer", []) if r.date >= cutoff
    ]:
        meta = r.metadata_ or {}
        for name, count in meta.get("installers", {}).items():
            all_installers[name] = all_installers.get(name, 0) + count
    installers = dict(sorted(all_installers.items(), key=lambda x: -x[1]))

    # Latest country breakdown (aggregate)
    all_countries: dict[str, int] = {}
    for r in [
        r for r in bulk.daily.get("downloads_by_country", []) if r.date >= cutoff
    ]:
        meta = r.metadata_ or {}
        for code, count in meta.get("countries", {}).items():
            all_countries[code] = all_countries.get(code, 0) + count
    countries = dict(sorted(all_countries.items(), key=lambda x: -x[1]))

    # Per-day per-version data
    version_daily_rows = [
        r for r in bulk.daily.get("downloads_by_version", []) if r.date >= cutoff
    ]
    version_daily: dict[str, dict[str, int]] = {}
    for r in version_daily_rows:
        day = str(r.date)[:10]
        meta = r.metadata_ or {}
        day_versions = meta.get("versions", {})
        version_daily[day] = {
            ver: split_downloads(info)[0] for ver, info in day_versions.items()
        }

    # Version breakdown with real human/bot
    versions: dict[str, dict[str, int]] = {}
    for r in version_daily_rows:
        meta = r.metadata_ or {}
        for ver, info in meta.get("versions", {}).items():
            total, human, _ = split_downloads(info)
            running = versions.setdefault(ver, {"total": 0, "human": 0})
            running["total"] += total
            running["human"] += human
    versions = dict(sorted(versions.items(), key=lambda x: -x[1]["total"]))

    # Distribution type breakdown
    all_types: dict[str, int] = {}
    for r in [r for r in bulk.daily.get("downloads_by_type", []) if r.date >= cutoff]:
        meta = r.metadata_ or {}
        for t, count in meta.get("types", {}).items():
            all_types[t] = all_types.get(t, 0) + count
    dist_types = dict(sorted(all_types.items(), key=lambda x: -x[1]))

    # Events for chart annotations
    all_events: list[tuple[str, str, str]] = []
    for r in bulk.events.get("releases", []):
        tag = (r.metadata_ or {}).get("tag", "")
        if tag:
            all_events.append((str(r.date)[:10], tag, "release"))
    for ev in [ev for ev in bulk.insight_events if ev.event_type in PYPI_EVENT_TYPES]:
        all_events.append((str(ev.date)[:10], ev.description[:60], ev.event_type))

    release_map: dict[str, str] = {}
    for date, label, _ in all_events:
        if date in release_map:
            release_map[date] += f"\n{label}"
        else:
            release_map[date] = label

    return {
        "total": total,
        "today_total": today_total,
        "today_human": today_human,
        "bot_percent": bot_pct,
        "prev_total": sum(
            int(r.value)
            for r in bulk.daily.get("downloads_daily", [])
            if prev_cutoff <= r.date < cutoff
        ),
        "prev_human": sum(
            int(r.value)
            for r in bulk.daily.get("downloads_daily_human", [])
            if prev_cutoff <= r.date < cutoff
        ),
        "daily": daily,
        "version_daily": version_daily,
        "installers": installers,
        "countries": countries,
        "versions": versions,
        "types": dist_types,
        "releases": release_map,
        "all_events": all_events,
    }
