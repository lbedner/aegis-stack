"""The Docs tab (Plausible): visitors, pages, countries, sources, spotlights."""

from __future__ import annotations

from typing import Any

from app.services.insights.schemas import (
    BulkInsightsResponse,
    PlausibleTopCountriesMetadata,
    PlausibleTopPagesMetadata,
    PlausibleTopSourcesMetadata,
)
from app.services.insights.schemas.views import (
    BreakdownItem,
    DailyValuePoint,
    DocsPageStats,
    DocsView,
    MetricCardView,
    SpotlightCard,
)
from app.services.insights.utils import range_cutoffs
from app.services.insights.views.events import all_events, event_type_options
from app.services.insights.views.formatting import (
    country_label,
    day_str,
    page_title,
    page_url,
    pct,
    referrer_url,
)


def build(bulk: BulkInsightsResponse, days: int = 14) -> DocsView:
    cutoff, prev_cutoff = range_cutoffs(days)

    def _split(key: str) -> tuple[list[Any], list[Any]]:
        rows = bulk.daily.get(key, [])
        cur = [r for r in rows if r.date >= cutoff]
        prev = [r for r in rows if prev_cutoff <= r.date < cutoff]
        return cur, prev

    visitors, prev_visitors = _split("visitors")
    pageviews, prev_pageviews = _split("pageviews")
    bounce_rows, prev_bounce = _split("bounce_rate")
    duration_rows, prev_duration = _split("avg_duration")

    # Top pages aggregate the per-day snapshots across the range. Visitors
    # and pageviews sum; time/bounce/scroll are visitor-weighted averages
    # so a low-traffic day cannot drag a high-traffic day's number.
    # Plausible only stores the path; the owning site comes from the
    # snapshot metadata for the click-through URL.
    page_totals: dict[str, dict[str, float]] = {}
    page_site: dict[str, str] = {}
    for r in (r for r in bulk.daily.get("top_pages", []) if r.date >= cutoff):
        meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
        try:
            parsed = PlausibleTopPagesMetadata.model_validate(meta)
        except Exception:
            continue
        for p in parsed.pages:
            entry = page_totals.setdefault(
                p.url,
                {
                    "visitors": 0.0,
                    "pageviews": 0.0,
                    # Running weighted sums: value * visitors, divided by
                    # total visitors at the end. Skipped when the field is
                    # None (Plausible did not report it that day).
                    "time_w": 0.0,
                    "time_visitors": 0.0,
                    "bounce_w": 0.0,
                    "bounce_visitors": 0.0,
                    "scroll_w": 0.0,
                    "scroll_visitors": 0.0,
                },
            )
            v = float(p.visitors or 0)
            entry["visitors"] += v
            entry["pageviews"] += float(p.pageviews or 0)
            if p.time_s is not None:
                entry["time_w"] += p.time_s * v
                entry["time_visitors"] += v
            if p.bounce_rate is not None:
                entry["bounce_w"] += p.bounce_rate * v
                entry["bounce_visitors"] += v
            if p.scroll is not None:
                entry["scroll_w"] += p.scroll * v
                entry["scroll_visitors"] += v
            page_site.setdefault(p.url, parsed.site)

    def _weighted(w: float, n: float) -> float | None:
        return (w / n) if n > 0 else None

    all_pages = sorted(
        [
            DocsPageStats(
                path=path,
                url=page_url(page_site.get(path, ""), path),
                visitors=int(v["visitors"]),
                pageviews=int(v["pageviews"]),
                time_s=_weighted(v["time_w"], v["time_visitors"]),
                bounce_rate=_weighted(v["bounce_w"], v["bounce_visitors"]),
                scroll=_weighted(v["scroll_w"], v["scroll_visitors"]),
            )
            for path, v in page_totals.items()
        ],
        key=lambda x: -x.visitors,
    )
    # The wire payload is capped at 10; spotlight cards still see the full
    # list so Most Read can surface a slow-burn page outside the top 10.
    top_pages = all_pages[:10]

    country_totals: dict[str, int] = {}
    for r in (r for r in bulk.daily.get("top_countries", []) if r.date >= cutoff):
        meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
        try:
            parsed_countries = PlausibleTopCountriesMetadata.model_validate(
                meta
            ).countries
        except Exception:
            continue
        for c in parsed_countries:
            country_totals[c.country] = country_totals.get(c.country, 0) + c.visitors
    # Full country list (with ISO codes) for the world map; top-10 for the
    # side table, the same shape as the PyPI tab.
    all_countries = [
        BreakdownItem(name=country_label(code), value=count, code=code)
        for code, count in sorted(country_totals.items(), key=lambda x: -x[1])
    ]
    top_countries = all_countries[:10]
    countries = all_countries[:50]

    # Top sources. Names look like "Direct / None", "Google", "github.com";
    # hostname shapes become click-throughs, the rest stay plain.
    source_totals: dict[str, int] = {}
    for r in (r for r in bulk.daily.get("top_sources", []) if r.date >= cutoff):
        meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
        try:
            parsed_sources = PlausibleTopSourcesMetadata.model_validate(meta).sources
        except Exception:
            continue
        for s in parsed_sources:
            source_totals[s.source] = source_totals.get(s.source, 0) + s.visitors
    top_sources = [
        BreakdownItem(name=name, value=count, url=referrer_url(name))
        for name, count in sorted(source_totals.items(), key=lambda x: -x[1])[:10]
    ]

    def _sum(rows: list[Any]) -> int:
        return int(sum(r.value for r in rows))

    def _avg(rows: list[Any]) -> int:
        return int(sum(r.value for r in rows) / len(rows)) if rows else 0

    total_visitors = _sum(visitors)
    total_pageviews = _sum(pageviews)
    views_per_visit = (
        round(total_pageviews / total_visitors, 1) if total_visitors else 0
    )
    avg_bounce = _avg(bounce_rows)
    avg_duration_s = _avg(duration_rows)
    duration_str = (
        f"{avg_duration_s // 60}m {avg_duration_s % 60}s"
        if avg_duration_s >= 60
        else f"{avg_duration_s}s"
    )

    prev_total_visitors = _sum(prev_visitors)
    prev_total_pageviews = _sum(prev_pageviews)
    prev_views_per_visit = (
        round(prev_total_pageviews / prev_total_visitors, 1)
        if prev_total_visitors
        else 0
    )
    prev_avg_bounce = _avg(prev_bounce)
    prev_avg_duration_s = _avg(prev_duration)

    metrics = [
        MetricCardView(
            label="Visitors",
            value=total_visitors,
            change_pct=pct(total_visitors, prev_total_visitors),
        ),
        MetricCardView(
            label="Pageviews",
            value=total_pageviews,
            change_pct=pct(total_pageviews, prev_total_pageviews),
        ),
        MetricCardView(
            label="Views/Visit",
            value=views_per_visit,
            change_pct=pct(views_per_visit, prev_views_per_visit),
        ),
        MetricCardView(
            label="Bounce Rate",
            value=f"{avg_bounce}%",
            change_pct=pct(avg_bounce, prev_avg_bounce),
            lower_is_better=True,
        ),
        MetricCardView(
            label="Avg Duration",
            value=duration_str,
            change_pct=pct(avg_duration_s, prev_avg_duration_s),
        ),
    ]

    events = all_events(bulk, days=days)
    return DocsView(
        metrics=metrics,
        visitors=[
            DailyValuePoint(date=day_str(r.date), value=int(r.value)) for r in visitors
        ],
        pageviews=[
            DailyValuePoint(date=day_str(r.date), value=int(r.value)) for r in pageviews
        ],
        top_pages=top_pages,
        top_countries=top_countries,
        countries=countries,
        top_sources=top_sources,
        spotlights=spotlights(all_pages, top_countries),
        events=events,
        event_types=event_type_options(events),
    )


def spotlights(
    pages: list[DocsPageStats], countries: list[BreakdownItem]
) -> list[SpotlightCard]:
    """Most Read / Most Visited / Top Country cards from the already
    aggregated page stats, so the raw Plausible metadata is not re-walked."""
    cards: list[SpotlightCard] = []
    content_pages = [p for p in pages if len(p.path.strip("/").split("/")) >= 2]
    read_pages = sorted(
        [p for p in content_pages if (p.time_s or 0) > 0],
        key=lambda p: -(p.time_s or 0),
    )
    by_visitors = sorted(content_pages, key=lambda p: -p.visitors)

    most_read_path = ""
    if read_pages:
        mr = read_pages[0]
        mr_time = int(mr.time_s or 0)
        most_read_path = mr.path
        cards.append(
            SpotlightCard(
                label="Most Read",
                value=page_title(mr.path),
                sublabel=f"{mr_time // 60}m {mr_time % 60}s read time",
                tooltip=mr.path,
            )
        )

    if by_visitors and by_visitors[0].path != most_read_path:
        tv = by_visitors[0]
        cards.append(
            SpotlightCard(
                label="Most Visited",
                value=page_title(tv.path),
                sublabel=f"{tv.visitors} visitors",
                tooltip=tv.path,
            )
        )

    if countries:
        top = countries[0]
        cards.append(
            SpotlightCard(
                label="Top Country", value=top.name, sublabel=f"{top.value} visitors"
            )
        )

    if len(countries) >= 2:
        cards.append(SpotlightCard(label="Top Countries", items=countries[:3]))

    return cards
