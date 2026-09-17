"""The GitHub traffic tab."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.data_table import (
    DataTable,
    DataTableColumn,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.views import InsightViewService
from app.services.insights.views.formatting import pct as pct_change
from app.services.insights.views.events import (
    GITHUB_EVENT_TYPES,
)

from ..modal_sections import (
    ChartColors,
    LineChartCard,
    LineSeries,
    MetricCard,
    chart_tooltip_kwargs,
)
from app.components.frontend.dashboard.modals.insights_modal.base import (
    InsightsTab,
)
from app.components.frontend.dashboard.modals.insights_modal.charts import (
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


class GitHubTrafficTab(InsightsTab):
    """GitHub traffic, events, and activity with date range and event annotations."""

    _default_days = 7

    # -- build content --------------------------------------------------------

    def _build_content(self) -> None:  # noqa: C901
        """Build or rebuild all content based on state."""
        data = self._data
        daily = data["daily"]

        last_date = daily[-1]["date"] if daily else ""
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_date),
            ft.Container(height=8),
        ]

        if not daily:
            content.append(SecondaryText("No GitHub traffic data collected yet."))
            self._content_column.controls = content
            return

        # Range-level aggregates
        total_clones = sum(d["clones"] for d in daily)
        total_unique = sum(d["unique_cloners"] for d in daily)
        total_views = sum(d["views"] for d in daily)
        total_visitors = sum(d["unique_visitors"] for d in daily)
        clone_ratio = total_clones / total_unique if total_unique > 0 else 0
        num_days = len(daily)
        range_label = next(
            (label for label, days in RANGE_OPTIONS if days == self._days),
            f"{self._days}d",
        )

        # Period-over-period change

        prev_c = data.get("prev_clones", 0)
        prev_u = data.get("prev_unique", 0)
        prev_v = data.get("prev_views", 0)
        prev_vis = data.get("prev_visitors", 0)

        # Latest day's values for subtitle
        last_day = daily[-1] if daily else {}
        last_clones = last_day.get("clones", 0)
        last_unique = last_day.get("unique_cloners", 0)
        last_views = last_day.get("views", 0)
        last_visitors = last_day.get("unique_visitors", 0)
        last_date = last_day.get("date", "")

        from datetime import datetime as _dt

        _days_ago = (
            (_dt.now() - _dt.strptime(last_date, "%Y-%m-%d")).days if last_date else 0
        )
        _day_label = (
            "today"
            if _days_ago == 0
            else "yesterday"
            if _days_ago == 1
            else f"{_days_ago}d ago"
        )

        # Metric cards — all on one row, always visible
        forks = data.get("forks", [])
        releases = data.get("releases", {})
        star_daily = data.get("star_events_daily", [])
        avg_stars = (
            sum(d["stars"] for d in star_daily) / len(star_daily) if star_daily else 0
        )

        # Previous period clone ratio
        prev_ratio = prev_c / prev_u if prev_u > 0 else 0
        prev_ratio_label = (
            f"prev: {prev_ratio:.1f}:1" if prev_ratio > 0 else f"in {range_label}"
        )

        # Previous period avg stars (from bulk data)
        from app.services.insights.domains.metrics import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(self._days)
        prev_star_rows = [
            r
            for r in self._bulk.daily.get("star_events", [])
            if prev_cutoff <= r.date < cutoff
        ]
        prev_avg_stars = (
            sum(int(r.value) for r in prev_star_rows) / len(prev_star_rows)
            if prev_star_rows
            else 0
        )
        prev_stars_label = (
            f"prev: {prev_avg_stars:.1f}" if prev_star_rows else f"in {range_label}"
        )

        content.append(
            ft.Row(
                [
                    MetricCard(
                        "Clones",
                        f"{total_clones:,}",
                        Theme.Colors.PRIMARY,
                        change_pct=pct_change(total_clones, prev_c),
                        prev_value=f"+{last_clones:,} {_day_label}",
                    ),
                    MetricCard(
                        "Unique",
                        f"{total_unique:,}",
                        Theme.Colors.INFO,
                        change_pct=pct_change(total_unique, prev_u),
                        prev_value=f"+{last_unique:,} {_day_label}",
                        tooltip="Unique cloners per day, counted independently by GitHub. Not deduplicated across days.",  # noqa: E501
                    ),
                    MetricCard(
                        "Views",
                        f"{total_views:,}",
                        Theme.Colors.SUCCESS,
                        change_pct=pct_change(total_views, prev_v),
                        prev_value=f"+{last_views:,} {_day_label}",
                    ),
                    MetricCard(
                        "Visitors",
                        f"{total_visitors:,}",
                        Theme.Colors.WARNING,
                        change_pct=pct_change(total_visitors, prev_vis),
                        prev_value=f"+{last_visitors:,} {_day_label}",
                    ),
                    MetricCard(
                        "Clone Ratio",
                        f"{clone_ratio:.1f}:1",
                        "#E91E63",
                        prev_value=prev_ratio_label,
                    ),
                    MetricCard(
                        "Forks",
                        str(len(forks)),
                        "#A855F7",
                        prev_value=f"in {range_label}",
                    ),
                    MetricCard(
                        "Releases",
                        str(len(releases)),
                        "#22C55E",
                        prev_value=f"in {range_label}",
                    ),
                    MetricCard(
                        "Avg Stars/Day",
                        f"{avg_stars:.1f}",
                        "#F59E0B",
                        prev_value=prev_stars_label,
                    ),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Date range text
        date_range = (
            f"{_pretty_date(daily[0]['date'])} \u2014 {_pretty_date(daily[-1]['date'])}"
        )
        content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

        # Event chips
        first_date = daily[0]["date"]
        last_date = daily[-1]["date"]
        window_events = [
            (date, label, etype)
            for date, label, etype in data.get("all_events", [])
            if first_date <= date <= last_date
        ]
        chips = self._render_event_chips(window_events)
        if chips:
            content.append(chips)

        content.append(ft.Container(height=4))

        # -- Clones + Unique chart with event annotations ---------------------

        highlighted = self._highlighted_dates

        # Trim leading zero days separately for each chart
        clone_daily = daily
        for i, d in enumerate(daily):
            if d["clones"] or d["unique_cloners"]:
                clone_daily = daily[i:]
                break

        view_daily = daily
        for i, d in enumerate(daily):
            if d["views"] or d["unique_visitors"]:
                view_daily = daily[i:]
                break

        # Build a date→event-labels map. The Events dropdown's selected
        # types narrow the set when non-empty (== filtered); an empty
        # set means "All", showing every event in the chart's tooltip
        # overlay.
        events_by_date: dict[str, list[str]] = {}
        for ev_date, ev_label, ev_etype in data.get("all_events", []):
            if (
                self._selected_event_types
                and ev_etype not in self._selected_event_types
            ):
                continue
            events_by_date.setdefault(ev_date, []).append(ev_label)

        # -- Clones + Unique chart --------------------------------------------
        # Indices on the chart that correspond to the currently selected
        # event chip — drives the per-point amber marker that lets the
        # eye correlate the chip with its date.
        clone_highlights = frozenset(
            i for i, d in enumerate(clone_daily) if d["date"] in highlighted
        )
        clone_series = [
            LineSeries(
                label="Clones",
                color=ChartColors.TEAL,
                points=[(i, d["clones"]) for i, d in enumerate(clone_daily)],
                tooltips=[f"Clones: {d['clones']:,}" for d in clone_daily],
                fill=True,
                highlighted_indices=clone_highlights,
            ),
            LineSeries(
                label="Unique Cloners",
                color=ChartColors.INDIGO,
                points=[(i, d["unique_cloners"]) for i, d in enumerate(clone_daily)],
                tooltips=[f"Unique: {d['unique_cloners']:,}" for d in clone_daily],
                highlighted_indices=clone_highlights,
            ),
        ]
        content.append(
            LineChartCard(
                title="Clones",
                subtitle="clones / unique cloners per day",
                x_labels=[d["date"] for d in clone_daily],
                series=clone_series,
                height=300,
                event_annotations=[
                    events_by_date.get(d["date"], []) for d in clone_daily
                ],
            )
        )

        content.append(ft.Container(height=12))

        # -- Views + Visitors chart -------------------------------------------
        view_highlights = frozenset(
            i for i, d in enumerate(view_daily) if d["date"] in highlighted
        )
        view_series = [
            LineSeries(
                label="Views",
                color=ChartColors.TEAL,
                points=[(i, d["views"]) for i, d in enumerate(view_daily)],
                tooltips=[f"Views: {d['views']:,}" for d in view_daily],
                fill=True,
                highlighted_indices=view_highlights,
            ),
            LineSeries(
                label="Visitors",
                color=ChartColors.VIOLET,
                points=[(i, d["unique_visitors"]) for i, d in enumerate(view_daily)],
                tooltips=[f"Visitors: {d['unique_visitors']:,}" for d in view_daily],
                highlighted_indices=view_highlights,
            ),
        ]
        content.append(
            LineChartCard(
                title="Views",
                subtitle="page views / unique visitors per day",
                x_labels=[d["date"] for d in view_daily],
                series=view_series,
                height=300,
                event_annotations=[
                    events_by_date.get(d["date"], []) for d in view_daily
                ],
            )
        )

        # Interpretation
        content.append(
            ft.Container(
                content=SecondaryText(
                    f"{range_label} clone ratio of {clone_ratio:.1f}:1 across {total_clones:,} clones "  # noqa: E501
                    f"from {total_unique:,} unique cloners. "
                    f"Traffic data covers {num_days} days.",
                    size=Theme.Typography.BODY_SMALL,
                ),
                padding=ft.padding.symmetric(horizontal=4, vertical=8),
            )
        )

        # -- Avg Unique Cloners by Day of Week --------------------------------
        # Source/cadence pattern lives here — peak/trough days are colored
        # distinctly so the rhythm pops without parsing seven nearly-equal
        # bars. Hidden when there's no cloner data at all.
        weekday = data.get("weekday", [])
        if weekday and any(v > 0 for v in weekday):
            wk_min = min(weekday)
            wk_max = max(weekday)
            pad_bottom = max((wk_max - wk_min) * 0.3, 1)
            pad_top = max((wk_max - wk_min) * 0.15, 1)
            wk_min_y = max(0, int(wk_min - pad_bottom))
            wk_max_y = int(wk_max + pad_top + 0.5)

            # Peak (brand teal) + trough (violet) + middle days (muted teal)
            # — same color treatment as the aegis-pulse Summary tab.
            peak_color = ChartColors.TEAL
            trough_color = ChartColors.VIOLET
            mid_color = ft.Colors.with_opacity(0.55, ChartColors.TEAL)

            wk_groups: list[ft.BarChartGroup] = []
            for i, v in enumerate(weekday):
                if v == wk_max:
                    bar_color = peak_color
                elif v == wk_min:
                    bar_color = trough_color
                else:
                    bar_color = mid_color
                wk_groups.append(
                    ft.BarChartGroup(
                        x=i,
                        bar_rods=[
                            ft.BarChartRod(
                                from_y=wk_min_y,
                                to_y=v,
                                width=28,
                                color=bar_color,
                                tooltip=f"{['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][i]}: {v:.1f}",
                                border_radius=4,
                            )
                        ],
                    )
                )

            # Y-axis ticks rendered explicitly so they pick up the same
            # small + muted styling as the bottom axis (and as the
            # LineChartCard left-axis treatment) — without this, Flet
            # falls back to its default-styled auto-labels which are
            # larger and use the default white text color.
            wk_step = _smart_step(wk_max_y - wk_min_y)
            wk_left_labels: list[ft.ChartAxisLabel] = []
            if wk_step > 0:
                tick = int(wk_min_y) + (
                    wk_step - (int(wk_min_y) % wk_step)
                    if int(wk_min_y) % wk_step
                    else 0
                )
                while tick <= wk_max_y:
                    wk_left_labels.append(
                        ft.ChartAxisLabel(
                            value=tick,
                            label=ft.Text(
                                f"{int(tick):,}",
                                size=9,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        )
                    )
                    tick += wk_step

            wk_chart = ft.BarChart(
                bar_groups=wk_groups,
                left_axis=ft.ChartAxis(labels_size=50, labels=wk_left_labels),
                bottom_axis=ft.ChartAxis(
                    labels_size=40,
                    labels=[
                        ft.ChartAxisLabel(
                            value=i,
                            label=ft.Text(
                                ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][i],
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        )
                        for i in range(7)
                    ],
                ),
                horizontal_grid_lines=ft.ChartGridLines(
                    color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                    width=1,
                ),
                **chart_tooltip_kwargs(),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                interactive=True,
                min_y=wk_min_y,
                max_y=wk_max_y,
                height=240,
                expand=True,
            )

            # Wrap in the same MetricCard-style card as the line charts
            # so the surfaces stay visually unified. Title row dropped
            # to match LineChartCard — the chart speaks for itself.
            content.append(ft.Container(height=12))
            content.append(
                ft.Container(
                    content=wk_chart,
                    padding=Theme.Spacing.MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border=ft.border.all(0.5, ft.Colors.OUTLINE),
                    border_radius=Theme.Components.CARD_RADIUS,
                )
            )

        # -- Referrers + Popular Paths ----------------------------------------
        # Side-by-side data tables, matching the aegis-pulse Summary tab.
        # Each name cell is a clickable link (referrer domain or
        # github.com path), so visitors can dig into the source from
        # the modal instead of copy-pasting URLs.
        referrers = data.get("referrers", [])
        paths = data.get("popular_paths", [])

        traffic_columns = [
            DataTableColumn("Source", style="primary"),
            DataTableColumn("Views", width=80, alignment="right", style="body"),
            DataTableColumn("Unique", width=80, alignment="right", style="secondary"),
        ]

        def _link_cell(label: str, url: str) -> ft.Container:
            return ft.Container(
                content=ft.Text(
                    label,
                    size=Theme.Typography.BODY,
                    style=ft.TextStyle(
                        color=Theme.Colors.INFO,
                        decoration=ft.TextDecoration.UNDERLINE,
                    ),
                    selectable=False,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                on_click=lambda e, u=url: e.page.launch_url(u),
                ink=True,
                expand=True,
            )

        referrer_rows = [
            [
                _link_cell(
                    ref["domain"],
                    f"https://{ref['domain']}"
                    if "." in ref["domain"]
                    else f"https://www.google.com/search?q={ref['domain']}",
                ),
                f"{ref['views']:,}",
                f"{ref['uniques']:,}",
            ]
            for ref in referrers
        ]

        paths_rows = [
            [
                _link_cell(p["path"], f"https://github.com{p['path']}"),
                f"{p['views']:,}",
                f"{p['uniques']:,}",
            ]
            for p in paths
        ]

        referrers_section = ft.Column(
            [
                H3Text("Referrers"),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                DataTable(
                    columns=traffic_columns,
                    rows=referrer_rows,
                    empty_message="No referrer data available.",
                ),
            ],
            spacing=6,
            expand=1,
        )
        paths_section = ft.Column(
            [
                H3Text("Popular Paths"),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                DataTable(
                    columns=traffic_columns,
                    rows=paths_rows,
                    empty_message="No popular path data available.",
                ),
            ],
            spacing=6,
            expand=1,
        )

        content.append(ft.Container(height=8))
        content.append(
            ft.Row(
                [referrers_section, paths_section],
                spacing=Theme.Spacing.LG,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

        self._content_column.controls = content

    # -- data loader ----------------------------------------------------------

    def _load_data(self, days: int = 14) -> dict[str, Any]:
        """Load GitHub data from bulk pre-loaded data with date cutoff."""
        from app.services.insights.domains.metrics import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

        # Traffic daily
        clones_rows = [
            r for r in self._bulk.daily.get("clones", []) if r.date >= cutoff
        ]
        unique_rows = [
            r for r in self._bulk.daily.get("unique_cloners", []) if r.date >= cutoff
        ]
        views_rows = [r for r in self._bulk.daily.get("views", []) if r.date >= cutoff]
        visitors_rows = [
            r for r in self._bulk.daily.get("unique_visitors", []) if r.date >= cutoff
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
        referrers_row = self._bulk.latest.get("referrers")
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
        paths_row = self._bulk.latest.get("popular_paths")
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
        fork_rows = [r for r in self._bulk.events.get("forks", []) if r.date >= cutoff]
        forks: list[dict[str, str]] = []
        for r in fork_rows:
            meta = r.metadata_ or {}
            forks.append(
                {"actor": meta.get("actor", "unknown"), "date": str(r.date)[:10]}
            )

        # Star events daily
        star_rows = [
            r for r in self._bulk.daily.get("star_events", []) if r.date >= cutoff
        ]
        star_events_daily: list[dict[str, Any]] = []
        for r in star_rows:
            star_events_daily.append({"date": str(r.date)[:10], "stars": int(r.value)})

        # Activity summary daily
        activity_rows = [
            r for r in self._bulk.daily.get("activity_summary", []) if r.date >= cutoff
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
        release_rows = [
            r for r in self._bulk.events.get("releases", []) if r.date >= cutoff
        ]
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
            for ev in self._bulk.insight_events
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
        github_view = InsightViewService(self._bulk).github(days=days)
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
                for r in self._bulk.daily.get("clones", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_unique": sum(
                int(r.value)
                for r in self._bulk.daily.get("unique_cloners", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_views": sum(
                int(r.value)
                for r in self._bulk.daily.get("views", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_visitors": sum(
                int(r.value)
                for r in self._bulk.daily.get("unique_visitors", [])
                if prev_cutoff <= r.date < cutoff
            ),
        }
