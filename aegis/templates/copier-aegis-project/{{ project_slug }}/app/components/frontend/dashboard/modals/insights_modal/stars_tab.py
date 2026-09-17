"""The stars tab."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.views.events import (
    GITHUB_EVENT_TYPES,
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


class StarsTab(InsightsTab):
    """Stars: cumulative chart, recent list, event chips — with date range."""

    _default_days = 7

    def _build_content(self) -> None:
        """Build or rebuild all content based on state."""
        data = self._data
        star_history = data["star_history"]
        total_stars = data["total_stars"]
        range_stars = data["range_stars"]

        last_date = star_history[-1]["date"] if star_history else ""
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_date),
            ft.Container(height=8),
        ]

        # Metric cards
        num_days = len(star_history) if star_history else 1
        avg_per_day = range_stars / num_days if num_days else 0

        content.append(
            ft.Row(
                [
                    MetricCard("Total Stars", str(total_stars), "#FFD700"),
                    MetricCard("In Range", str(range_stars), Theme.Colors.INFO),
                    MetricCard("Avg / Day", f"{avg_per_day:.1f}", Theme.Colors.SUCCESS),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        if not star_history:
            content.append(SecondaryText("No star events in this range."))
            self._content_column.controls = content
            return

        # Date range text
        date_range = f"{_pretty_date(star_history[0]['date'])} \u2014 {_pretty_date(star_history[-1]['date'])}"  # noqa: E501
        content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

        # Event chips — only on dates with stars, exclude star type
        star_dates = {d["date"] for d in star_history}
        chips = self._render_event_chips(
            data.get("all_events", []),
            valid_dates=star_dates,
            exclude_types={"star"},
        )
        if chips:
            content.append(chips)

        # Star History cumulative chart
        max_stars = star_history[-1]["stars"]
        min_stars = star_history[0]["stars"]
        padding = max(1, (max_stars - min_stars) // 4)
        star_min_y = max(0, min_stars - padding)
        star_range = max_stars - star_min_y
        star_step = _smart_step(star_range)
        star_max_y = int((max_stars // star_step + 1) * star_step)
        highlighted = self._highlighted_dates
        # Filter releases: exclude star events, only dates that have chart points
        releases_map = data.get("releases", {})
        non_star_releases: dict[str, str] = {}
        for day, label in releases_map.items():
            if day not in star_dates:
                continue
            lines = [ln for ln in label.split("\n") if not ln.startswith("\u2b50")]
            if lines:
                non_star_releases[day] = "\n".join(lines)

        history_points: list[ft.LineChartDataPoint] = []
        release_anno: list[ft.LineChartDataPoint] = []

        for i, d in enumerate(star_history):
            is_hl = d["date"] in highlighted
            hl_point = ChartPoint.highlight() if is_hl else None
            count = d.get("count", 1)
            names = d.get("usernames", [])
            if count == 1:
                tip = f"#{d['stars']} — {names[0] if names else ''}\n{_pretty_date(d['date'])}"  # noqa: E501
            else:
                first_num = d["stars"] - count + 1
                tip = f"#{first_num}-#{d['stars']} ({count} stars)\n{_pretty_date(d['date'])}"  # noqa: E501
            history_points.append(
                ft.LineChartDataPoint(
                    i,
                    d["stars"],
                    tooltip=tip,
                    point=hl_point,
                )
            )

            rel = non_star_releases.get(d["date"])
            if rel:
                release_anno.append(
                    ft.LineChartDataPoint(i, 0, tooltip=rel, show_tooltip=True)
                )
            else:
                release_anno.append(ft.LineChartDataPoint(i, 0, show_tooltip=False))

        chart_series = [
            ft.LineChartData(
                data_points=history_points,
                stroke_width=3,
                color=ChartColors.TEAL,
                curved=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.15, ChartColors.TEAL),
                point=ChartPoint.dot(ChartColors.TEAL),
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

        history_chart = _make_line_chart(
            chart_series, star_max_y, star_history, star_step, min_y=star_min_y
        )
        content.append(
            ft.Container(content=history_chart, margin=ft.margin.only(right=20))
        )
        content.append(_make_legend([(ChartColors.TEAL, "Cumulative Stars")]))

        self._content_column.controls = content

    def _load_data(self, days: int = 9999) -> dict[str, Any]:
        """Load star data from bulk pre-loaded data with date cutoff."""
        from app.services.insights.domains.metrics import InsightQueryService

        cutoff, _ = InsightQueryService.compute_cutoffs(days)

        # All stars (for total count)
        all_rows = self._bulk.events.get("new_star", [])
        total_stars = len(all_rows)

        if not all_rows:
            return {
                "star_history": [],
                "stars_recent": [],
                "total_stars": 0,
                "range_stars": 0,
                "all_events": [],
                "releases": {},
            }

        # Stars in range
        range_rows = [r for r in all_rows if r.date >= cutoff]
        range_stars = len(range_rows)

        # Cumulative history - only days with stars, within range
        by_date: dict[str, dict[str, Any]] = {}
        for r in range_rows:
            day = str(r.date)[:10]
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            if day not in by_date:
                by_date[day] = {"max_num": 0, "count": 0, "usernames": []}
            by_date[day]["max_num"] = max(by_date[day]["max_num"], int(r.value))
            by_date[day]["count"] += 1
            by_date[day]["usernames"].append(meta.get("username", "unknown"))
        star_history = [
            {
                "date": d,
                "stars": info["max_num"],
                "count": info["count"],
                "usernames": info["usernames"],
            }
            for d, info in sorted(by_date.items())
        ]

        # Recent stars (last 20 in range)
        stars_recent: list[dict[str, Any]] = []
        for r in reversed(range_rows[-20:]):
            meta = r.metadata_ if isinstance(r.metadata_, dict) else {}
            stars_recent.append(
                {
                    "number": int(r.value),
                    "username": meta.get("username", "unknown"),
                    "location": meta.get("location", ""),
                    "company": meta.get("company", ""),
                    "date": str(r.date)[:10],
                }
            )

        # Events for chips + chart annotations
        all_events: list[tuple[str, str, str]] = []
        for r in self._bulk.events.get("releases", []):
            tag = (r.metadata_ or {}).get("tag", "")
            if tag:
                all_events.append((str(r.date)[:10], tag, "release"))
        cutoff_str = str(cutoff.date())
        for ev in [
            ev
            for ev in self._bulk.insight_events
            if str(ev.date)[:10] >= cutoff_str and ev.event_type in GITHUB_EVENT_TYPES
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
            "star_history": star_history,
            "stars_recent": stars_recent,
            "total_stars": total_stars,
            "range_stars": range_stars,
            "all_events": all_events,
            "releases": release_map,
        }
