"""Turning the bulk payload into what the docs tab shows."""

from __future__ import annotations  # noqa: I001

from typing import Any

from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.views.events import (
    DOCS_EVENT_TYPES,
)


def plausible_data(bulk: BulkInsightsResponse, days: int = 30) -> dict[str, Any]:
    """Load Plausible data from bulk pre-loaded data."""
    from app.services.insights.domains.metrics import InsightQueryService

    cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

    # Daily metrics - current period
    visitors_rows = [r for r in bulk.daily.get("visitors", []) if r.date >= cutoff]
    pageviews_rows = [r for r in bulk.daily.get("pageviews", []) if r.date >= cutoff]
    duration_rows = [r for r in bulk.daily.get("avg_duration", []) if r.date >= cutoff]
    bounce_rows = [r for r in bulk.daily.get("bounce_rate", []) if r.date >= cutoff]

    # Previous period totals for comparison
    prev_visitors = sum(
        int(r.value)
        for r in bulk.daily.get("visitors", [])
        if prev_cutoff <= r.date < cutoff
    )
    prev_pageviews = sum(
        int(r.value)
        for r in bulk.daily.get("pageviews", [])
        if prev_cutoff <= r.date < cutoff
    )
    prev_dur_rows = [
        r for r in bulk.daily.get("avg_duration", []) if prev_cutoff <= r.date < cutoff
    ]
    prev_duration = (
        sum(float(r.value) for r in prev_dur_rows) / len(prev_dur_rows)
        if prev_dur_rows
        else 0
    )
    prev_bounce_rows = [
        r for r in bulk.daily.get("bounce_rate", []) if prev_cutoff <= r.date < cutoff
    ]
    prev_bounce = (
        sum(float(r.value) for r in prev_bounce_rows) / len(prev_bounce_rows)
        if prev_bounce_rows
        else 0
    )

    pv_map = {str(r.date)[:10]: int(r.value) for r in pageviews_rows}
    dur_map = {str(r.date)[:10]: float(r.value) for r in duration_rows}
    bounce_map = {str(r.date)[:10]: float(r.value) for r in bounce_rows}

    daily: list[dict[str, Any]] = []
    last_collected = ""
    for r in visitors_rows:
        day = str(r.date)[:10]
        visitors = int(r.value)
        pageviews = pv_map.get(day, 0)
        # Skip days with no activity to avoid dead space on chart
        if visitors == 0 and pageviews == 0:
            continue
        last_collected = day
        daily.append(
            {
                "date": day,
                "visitors": visitors,
                "pageviews": pageviews,
                "avg_duration": dur_map.get(day, 0),
                "bounce_rate": bounce_map.get(day, 0),
            }
        )

    # Top pages - aggregate per-day snapshots across selected range.
    # `visitors` and `pageviews` are sums; `time_s`, `bounce_rate`,
    # `scroll` are visitor-weighted averages (so a page with 100
    # visitors at 30s and 1 visitor at 300s reports the right
    # average, not (30+300)/2). Sorted by visitors desc to match
    # the header sort indicator on the pulse layout.
    all_pages: dict[str, dict[str, Any]] = {}
    for r in [r for r in bulk.daily.get("top_pages", []) if r.date >= cutoff]:
        meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
        for p in meta.get("pages", []):
            url = p.get("url", "")
            if not url:
                continue
            accum = all_pages.setdefault(
                url,
                {
                    "url": url,
                    "visitors": 0,
                    "pageviews": 0,
                    "_time_weighted": 0.0,
                    "_time_weight": 0,
                    "_bounce_weighted": 0.0,
                    "_bounce_weight": 0,
                    "_scroll_weighted": 0.0,
                    "_scroll_weight": 0,
                },
            )
            visitors = p.get("visitors", 0) or 0
            accum["visitors"] += visitors
            accum["pageviews"] += p.get("pageviews", 0) or 0

            if visitors > 0:
                if p.get("time_s") is not None:
                    accum["_time_weighted"] += float(p["time_s"]) * visitors
                    accum["_time_weight"] += visitors
                if p.get("bounce_rate") is not None:
                    accum["_bounce_weighted"] += float(p["bounce_rate"]) * visitors
                    accum["_bounce_weight"] += visitors
                if p.get("scroll") is not None:
                    accum["_scroll_weighted"] += float(p["scroll"]) * visitors
                    accum["_scroll_weight"] += visitors

    top_pages: list[dict[str, Any]] = []
    for accum in all_pages.values():
        tw = accum.pop("_time_weighted")
        twn = accum.pop("_time_weight")
        bw = accum.pop("_bounce_weighted")
        bwn = accum.pop("_bounce_weight")
        sw = accum.pop("_scroll_weighted")
        swn = accum.pop("_scroll_weight")
        accum["time_s"] = tw / twn if twn else 0.0
        accum["bounce_rate"] = bw / bwn if bwn else None
        accum["scroll"] = sw / swn if swn else None
        top_pages.append(accum)
    top_pages.sort(key=lambda x: -x["visitors"])
    top_pages = top_pages[:20]

    # Countries - aggregate per-day snapshots across selected range
    all_countries: dict[str, int] = {}
    for r in [r for r in bulk.daily.get("top_countries", []) if r.date >= cutoff]:
        meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
        for c in meta.get("countries", []):
            code = c.get("country", "")
            all_countries[code] = all_countries.get(code, 0) + c.get("visitors", 0)
    countries = [
        {"country": code, "visitors": count}
        for code, count in sorted(all_countries.items(), key=lambda x: -x[1])
    ][:20]

    # Sources - aggregate per-day snapshots across selected range.
    # Source labels come from the Plausible referrer breakdown
    # ("Direct / None", "GitHub", "Reddit", ...) - pre-formatted.
    all_sources: dict[str, int] = {}
    for r in [r for r in bulk.daily.get("top_sources", []) if r.date >= cutoff]:
        meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
        for s in meta.get("sources", []):
            name = s.get("source", "") or "Direct / None"
            all_sources[name] = all_sources.get(name, 0) + s.get("visitors", 0)
    top_sources = [
        {"source": name, "visitors": count}
        for name, count in sorted(all_sources.items(), key=lambda x: -x[1])
    ][:20]

    # Events
    all_events: list[tuple[str, str, str]] = []
    for r in bulk.events.get("releases", []):
        tag = (r.metadata_ or {}).get("tag", "")
        if tag:
            all_events.append((str(r.date)[:10], tag, "release"))
    cutoff_str = str(cutoff.date())
    for ev in [
        ev
        for ev in bulk.insight_events
        if str(ev.date)[:10] >= cutoff_str and ev.event_type in DOCS_EVENT_TYPES
    ]:
        all_events.append((str(ev.date)[:10], ev.description[:60], ev.event_type))

    release_map: dict[str, str] = {}
    for date, label, _ in all_events:
        if date in release_map:
            release_map[date] += f"\n{label}"
        else:
            release_map[date] = label

    all_events.sort(key=lambda x: x[0])

    return {
        "daily": daily,
        "top_pages": top_pages,
        "countries": countries,
        "top_sources": top_sources,
        "all_events": all_events,
        "releases": release_map,
        "prev_visitors": prev_visitors,
        "prev_pageviews": prev_pageviews,
        "prev_bounce": prev_bounce,
        "prev_duration": prev_duration,
        "last_collected": last_collected,
    }
