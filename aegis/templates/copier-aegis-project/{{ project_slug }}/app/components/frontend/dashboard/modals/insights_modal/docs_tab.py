"""The docs analytics tab."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    SecondaryText,
)
from app.components.frontend.controls.data_table import (
    DataTable,
    DataTableColumn,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.constants import country_label
from app.services.insights.views.formatting import pct as pct_change
from app.services.insights.views.events import (
    DOCS_EVENT_TYPES,
)

from ..modal_sections import (
    ChartColors,
    ChartPoint,
    MetricCard,
)
from app.components.frontend.dashboard.modals.insights_modal.base import (
    InsightsTab,
)
from app.components.frontend.dashboard.modals.insights_modal.charts import (
    _make_legend,
    _make_line_chart,
    _pretty_date,
    _smart_step,
)


# Event type → chip border/highlight color
EVENT_TYPE_COLORS: dict[str, str] = {
    "release": "#22C55E",
    "fork": "#A855F7",
    "star": "#F59E0B",
    "reddit_post": "#FF5722",
    "localization": "#3B82F6",
    "feature": "#06B6D4",
    "milestone_github": "#EC4899",
    "milestone_pypi": "#EC4899",
    "anomaly_github": "#EF4444",
    "external": "#9CA3AF",
}

# Shared date range options for all tabs
RANGE_OPTIONS = [
    ("7d", 7),
    ("14d", 14),
    ("1m", 30),
    ("3m", 90),
    ("6m", 180),
    ("1y", 365),
    ("All", 9999),
]

# Milestone category config (for Overview trophy cards)
CATEGORY_CONFIG: dict[str, dict[str, str]] = {
    "daily_clones": {"label": "GitHub 1-Day Clones", "color": "#2563eb"},
    "daily_unique": {"label": "GitHub 1-Day Unique", "color": "#A855F7"},
    "daily_views": {"label": "GitHub 1-Day Views", "color": "#22C55E"},
    "daily_visitors": {"label": "GitHub 1-Day Visitors", "color": "#F59E0B"},
    "14d_clones": {"label": "GitHub 14-Day Clones", "color": "#06B6D4"},
    "14d_unique": {"label": "GitHub 14-Day Unique", "color": "#EC4899"},
    "14d_visitors": {"label": "GitHub 14-Day Visitors", "color": "#F97316"},
    "pypi_daily": {"label": "PyPI Best Single Day", "color": "#EF4444"},
    "plausible_daily_visitors": {"label": "Docs 1-Day Visitors", "color": "#6366F1"},
    "plausible_daily_pageviews": {"label": "Docs 1-Day Pageviews", "color": "#22C55E"},
    "star_daily": {"label": "Stars Best Day", "color": "#FFD700"},
    "star_monthly": {"label": "Stars Best Month", "color": "#FFD700"},
}

# Event type to status mapping (for activity feed dot colors)
EVENT_STATUS_MAP: dict[str, str] = {
    "release": "success",
    "star": "warning",
    "reddit_post": "info",
    "milestone_github": "warning",
    "milestone_pypi": "warning",
    "feature": "info",
    "anomaly_github": "error",
    "external": "info",
}


class DocsTab(InsightsTab):
    """Docs analytics from Plausible with date range and event annotations."""

    _default_days = 7

    def _build_content(self) -> None:
        """Build or rebuild all content."""
        data = self._data
        daily = data["daily"]

        last_collected = data.get("last_collected", "")
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_collected),
            ft.Container(height=8),
        ]

        if not daily:
            content.append(
                SecondaryText(
                    "No Plausible data collected yet. Run: my-app insights collect plausible"  # noqa: E501
                )
            )
            self._content_column.controls = content
            return

        # Aggregates over range
        total_visitors = sum(d["visitors"] for d in daily)
        total_pageviews = sum(d["pageviews"] for d in daily)
        num_days = len(daily)
        avg_bounce = sum(d["bounce_rate"] for d in daily) / num_days if num_days else 0
        avg_duration = (
            sum(d["avg_duration"] for d in daily) / num_days if num_days else 0
        )
        views_per_visit = total_pageviews / total_visitors if total_visitors else 0
        duration_min = int(avg_duration // 60)
        duration_sec = int(avg_duration % 60)

        # Period-over-period change
        prev_v = data.get("prev_visitors", 0)
        prev_pv = data.get("prev_pageviews", 0)
        prev_b = data.get("prev_bounce", 0)
        prev_d = data.get("prev_duration", 0)

        # Metric cards with change arrows
        content.append(
            ft.Row(
                [
                    MetricCard(
                        "Visitors",
                        f"{total_visitors:,}",
                        ChartColors.TEAL,
                        change_pct=pct_change(total_visitors, prev_v),
                    ),
                    MetricCard(
                        "Pageviews",
                        f"{total_pageviews:,}",
                        ChartColors.INDIGO,
                        change_pct=pct_change(total_pageviews, prev_pv),
                    ),
                    MetricCard(
                        "Views/Visit", f"{views_per_visit:.1f}", Theme.Colors.SUCCESS
                    ),
                    MetricCard(
                        "Bounce Rate",
                        f"{avg_bounce:.0f}%",
                        Theme.Colors.WARNING if avg_bounce > 50 else Theme.Colors.INFO,
                        change_pct=pct_change(avg_bounce, prev_b),
                        invert=True,
                    ),
                    MetricCard(
                        "Avg Duration",
                        f"{duration_min}m {duration_sec}s",
                        "#A855F7",
                        change_pct=pct_change(avg_duration, prev_d),
                    ),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Insight cards: Most Read, Most Visited, Top Country
        top_pages = data.get("top_pages", [])
        countries = data.get("countries", [])
        insight_cards: list[ft.Control] = []

        if top_pages:

            def _page_title(url: str) -> str:
                parts = [p for p in url.strip("/").split("/") if p]
                return parts[-1].replace("-", " ").title() if parts else "Home"

            content_pages = [
                p for p in top_pages if len(p["url"].strip("/").split("/")) >= 2
            ]
            read_pages = [p for p in content_pages if (p.get("time_s") or 0) > 0]
            by_visitors = sorted(content_pages, key=lambda x: -x["visitors"])

            # Card 1: Most Read (highest time_s)
            if read_pages:
                mr = read_pages[0]
                mr_time = mr.get("time_s") or 0
                mr_min = int(mr_time // 60)
                mr_sec = int(mr_time % 60)
                insight_cards.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                SecondaryText("Most Read"),
                                ft.Text(
                                    _page_title(mr["url"]),
                                    size=24,
                                    weight=ft.FontWeight.W_600,
                                ),
                                SecondaryText(
                                    f"{mr_min}m {mr_sec}s read time",
                                    size=Theme.Typography.BODY_SMALL,
                                ),
                            ],
                            spacing=Theme.Spacing.XS,
                        ),
                        padding=Theme.Spacing.MD,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=Theme.Components.CARD_RADIUS,
                        border=ft.border.all(0.5, ft.Colors.OUTLINE),
                        expand=True,
                        tooltip=mr["url"],
                    )
                )

            # Card 2: Most Visited (highest visitors, if different from Most Read)
            most_read_url = read_pages[0]["url"] if read_pages else ""
            if by_visitors and by_visitors[0]["url"] != most_read_url:
                tv = by_visitors[0]
                insight_cards.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                SecondaryText("Most Visited"),
                                ft.Text(
                                    _page_title(tv["url"]),
                                    size=24,
                                    weight=ft.FontWeight.W_600,
                                ),
                                SecondaryText(
                                    f"{tv['visitors']} visitors",
                                    size=Theme.Typography.BODY_SMALL,
                                ),
                            ],
                            spacing=Theme.Spacing.XS,
                        ),
                        padding=Theme.Spacing.MD,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=Theme.Components.CARD_RADIUS,
                        border=ft.border.all(0.5, ft.Colors.OUTLINE),
                        expand=True,
                        tooltip=tv["url"],
                    )
                )

        # Card 3: Top Country
        if countries:
            top_country = countries[0]
            insight_cards.append(
                ft.Container(
                    content=ft.Column(
                        [
                            SecondaryText("Top Country"),
                            ft.Text(
                                country_label(top_country["country"]),
                                size=24,
                                weight=ft.FontWeight.W_600,
                            ),
                            SecondaryText(
                                f"{top_country['visitors']} visitors",
                                size=Theme.Typography.BODY_SMALL,
                            ),
                        ],
                        spacing=Theme.Spacing.XS,
                    ),
                    padding=Theme.Spacing.MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=Theme.Components.CARD_RADIUS,
                    border=ft.border.all(0.5, ft.Colors.OUTLINE),
                    expand=True,
                )
            )

        # Card 4: Top 3 Countries
        if len(countries) >= 2:
            country_items: list[ft.Control] = []
            for i, c in enumerate(countries[:3], 1):
                country_items.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                SecondaryText(
                                    f"#{i}", size=Theme.Typography.BODY_SMALL
                                ),
                                BodyText(
                                    country_label(c["country"]),
                                    size=Theme.Typography.BODY_SMALL,
                                ),
                                ft.Container(expand=True),
                                SecondaryText(
                                    f"{c['visitors']}", size=Theme.Typography.BODY_SMALL
                                ),
                            ],
                            spacing=4,
                        ),
                    )
                )
            insight_cards.append(
                ft.Container(
                    content=ft.Column(
                        [
                            SecondaryText("Top Countries"),
                            *country_items,
                        ],
                        spacing=Theme.Spacing.XS,
                    ),
                    padding=Theme.Spacing.MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=Theme.Components.CARD_RADIUS,
                    border=ft.border.all(0.5, ft.Colors.OUTLINE),
                    expand=True,
                )
            )

        if insight_cards:
            content.append(ft.Container(height=8))
            content.append(ft.Row(insight_cards, spacing=Theme.Spacing.MD))

        # Date range
        date_range = (
            f"{_pretty_date(daily[0]['date'])} \u2014 {_pretty_date(daily[-1]['date'])}"
        )
        content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

        # Event chips — only on days with visitor activity
        active_dates = {d["date"] for d in daily}
        chips = self._render_event_chips(
            data.get("all_events", []), valid_dates=active_dates
        )
        if chips:
            content.append(chips)

        content.append(ft.Container(height=4))

        # Visitors + Pageviews chart
        highlighted = self._highlighted_dates
        releases_map = {
            day: label
            for day, label in (data.get("releases", {})).items()
            if day in active_dates
        }

        max_val = max(
            max(d["pageviews"] for d in daily), max(d["visitors"] for d in daily)
        )
        step = _smart_step(max_val)
        max_y = int((max_val // step + 1) * step)

        visitor_points: list[ft.LineChartDataPoint] = []
        pageview_points: list[ft.LineChartDataPoint] = []
        release_anno: list[ft.LineChartDataPoint] = []

        for i, d in enumerate(daily):
            is_hl = d["date"] in highlighted
            hl_point = ChartPoint.highlight() if is_hl else None

            visitor_points.append(
                ft.LineChartDataPoint(
                    i,
                    d["visitors"],
                    tooltip=f"Visitors: {d['visitors']}",
                    point=hl_point,
                )
            )
            pageview_points.append(
                ft.LineChartDataPoint(
                    i,
                    d["pageviews"],
                    tooltip=f"Pageviews: {d['pageviews']}",
                )
            )

            rel = releases_map.get(d["date"])
            if rel:
                release_anno.append(
                    ft.LineChartDataPoint(i, 0, tooltip=rel, show_tooltip=True)
                )
            else:
                release_anno.append(ft.LineChartDataPoint(i, 0, show_tooltip=False))

        # Match the aegis-pulse Docs panel: Visitors as the filled
        # primary series (teal), Pageviews as a line on top (indigo).
        # Same visual grammar as the GitHub Clones+Unique chart and the
        # PyPI Total+Human chart, so all three "primary + companion"
        # series read the same way across the modal.
        chart_series = [
            ft.LineChartData(
                data_points=visitor_points,
                stroke_width=2,
                color=ChartColors.TEAL,
                curved=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.15, ChartColors.TEAL),
                stroke_cap_round=True,
            ),
            ft.LineChartData(
                data_points=pageview_points,
                stroke_width=2,
                color=ChartColors.INDIGO,
                curved=True,
                stroke_cap_round=True,
            ),
        ]
        if any(p.show_tooltip for p in release_anno):
            chart_series.append(
                ft.LineChartData(
                    data_points=release_anno,
                    stroke_width=0,
                    color="#9CA3AF",
                )
            )

        chart = _make_line_chart(chart_series, max_y, daily, step)
        content.append(ft.Container(content=chart, margin=ft.margin.only(right=20)))
        content.append(
            _make_legend(
                [
                    (ChartColors.TEAL, "Visitors"),
                    (ChartColors.INDIGO, "Pageviews"),
                ]
            )
        )

        # Top Pages table - six-column `DataTable` matching the pulse
        # PAGE / VISITORS / PAGEVIEWS / BOUNCE / TIME / SCROLL layout.
        # Title sits in the first column header (same convention as the
        # bottom Top Countries / Top Sources cards), so the whole card
        # reads as one unit.
        top_pages = data.get("top_pages", [])
        if top_pages:

            def _format_duration(seconds: float) -> str:
                d_min = int(seconds // 60)
                d_sec = int(seconds % 60)
                return f"{d_min}m {d_sec}s" if d_min else f"{d_sec}s"

            def _formatpct(value: float | None) -> str:
                return "-" if value is None else f"{value:.1f}%"

            def _page_link(url: str) -> ft.Container:
                full_url = f"https://lbedner.github.io{url}"
                return ft.Container(
                    content=ft.Text(
                        url,
                        size=Theme.Typography.BODY,
                        style=ft.TextStyle(
                            color=Theme.Colors.INFO,
                            decoration=ft.TextDecoration.UNDERLINE,
                        ),
                        selectable=False,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    on_click=lambda e, u=full_url: e.page.launch_url(u),
                    ink=True,
                    expand=True,
                )

            pages_columns = [
                DataTableColumn("TOP PAGES", style="primary"),
                DataTableColumn("VISITORS", width=80, alignment="right", style="body"),
                DataTableColumn(
                    "PAGEVIEWS", width=90, alignment="right", style="secondary"
                ),
                DataTableColumn(
                    "BOUNCE", width=70, alignment="right", style="secondary"
                ),
                DataTableColumn("TIME", width=70, alignment="right", style="secondary"),
                DataTableColumn(
                    "SCROLL", width=70, alignment="right", style="secondary"
                ),
            ]
            pages_rows = [
                [
                    _page_link(p["url"]),
                    f"{p['visitors']:,}",
                    f"{p['pageviews']:,}",
                    _formatpct(p.get("bounce_rate")),
                    _format_duration(p.get("time_s") or 0),
                    _formatpct(p.get("scroll")),
                ]
                for p in top_pages
            ]

            content.append(ft.Container(height=12))
            content.append(
                DataTable(
                    columns=pages_columns,
                    rows=pages_rows,
                    empty_message="No page data available.",
                )
            )

        # Top Countries + Top Sources - two side-by-side `DataTable`s.
        # Title lives in the table header (first column) rather than as
        # a separate `H3Text`, so the card reads as one unit instead of
        # a heading + table stack. Sits at the bottom because it's the
        # long-tail "where is the traffic actually coming from?" view;
        # metrics + chart answer the headline question first.
        top_sources = data.get("top_sources", [])
        if countries or top_sources:
            countries_table = DataTable(
                columns=[
                    DataTableColumn("TOP COUNTRIES", style="primary"),
                    DataTableColumn("", width=80, alignment="right", style="body"),
                ],
                rows=[
                    [
                        country_label(c["country"]),
                        f"{c['visitors']:,}",
                    ]
                    for c in countries[:7]
                ],
                empty_message="No country data available.",
            )
            sources_table = DataTable(
                columns=[
                    DataTableColumn("TOP SOURCES", style="primary"),
                    DataTableColumn("", width=80, alignment="right", style="body"),
                ],
                rows=[[s["source"], f"{s['visitors']:,}"] for s in top_sources[:7]],
                empty_message="No source data available.",
            )

            content.append(ft.Container(height=8))
            content.append(
                ft.Row(
                    [
                        ft.Container(content=countries_table, expand=1),
                        ft.Container(content=sources_table, expand=1),
                    ],
                    spacing=Theme.Spacing.LG,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

        self._content_column.controls = content

    def _load_data(self, days: int = 30) -> dict[str, Any]:
        """Load Plausible data from bulk pre-loaded data."""
        from app.services.insights.domains.metrics import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

        # Daily metrics - current period
        visitors_rows = [
            r for r in self._bulk.daily.get("visitors", []) if r.date >= cutoff
        ]
        pageviews_rows = [
            r for r in self._bulk.daily.get("pageviews", []) if r.date >= cutoff
        ]
        duration_rows = [
            r for r in self._bulk.daily.get("avg_duration", []) if r.date >= cutoff
        ]
        bounce_rows = [
            r for r in self._bulk.daily.get("bounce_rate", []) if r.date >= cutoff
        ]

        # Previous period totals for comparison
        prev_visitors = sum(
            int(r.value)
            for r in self._bulk.daily.get("visitors", [])
            if prev_cutoff <= r.date < cutoff
        )
        prev_pageviews = sum(
            int(r.value)
            for r in self._bulk.daily.get("pageviews", [])
            if prev_cutoff <= r.date < cutoff
        )
        prev_dur_rows = [
            r
            for r in self._bulk.daily.get("avg_duration", [])
            if prev_cutoff <= r.date < cutoff
        ]
        prev_duration = (
            sum(float(r.value) for r in prev_dur_rows) / len(prev_dur_rows)
            if prev_dur_rows
            else 0
        )
        prev_bounce_rows = [
            r
            for r in self._bulk.daily.get("bounce_rate", [])
            if prev_cutoff <= r.date < cutoff
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
        for r in [r for r in self._bulk.daily.get("top_pages", []) if r.date >= cutoff]:
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
        for r in [
            r for r in self._bulk.daily.get("top_countries", []) if r.date >= cutoff
        ]:
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
        for r in [
            r for r in self._bulk.daily.get("top_sources", []) if r.date >= cutoff
        ]:
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
        for r in self._bulk.events.get("releases", []):
            tag = (r.metadata_ or {}).get("tag", "")
            if tag:
                all_events.append((str(r.date)[:10], tag, "release"))
        cutoff_str = str(cutoff.date())
        for ev in [
            ev
            for ev in self._bulk.insight_events
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
