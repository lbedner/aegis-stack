"""The Overview tab: hero numbers, goals, and the activity feed."""

from __future__ import annotations  # noqa: I001

from typing import Any

from datetime import datetime, timedelta

import flet as ft

from .overview_sections import (
    _build_overview_goals,
    _build_overview_hero,
    sum_in_range,
)

from app.components.frontend.dashboard.modals.insights_modal.charts import (
    trim_leading_zeros,
)

from app.components.frontend.dashboard.modals.insights_modal.constants import (
    EVENT_STATUS_MAP,
)

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.data_table import (
    DataTableColumn,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.views import InsightViewService
from app.services.insights.views.formatting import pct as pct_change

from ..modal_sections import (
    ChartColors,
    LineChartCard,
    LineSeries,
    MetricCard,
)


# Event type → chip border/highlight color

# Shared date range options for all tabs

# Milestone category config (for Overview trophy cards)

# Event type to status mapping (for activity feed dot colors)


class OverviewTab(ft.Container):
    """Overview: key metrics, milestones, recent events, source status."""

    def __init__(
        self,
        metadata: dict[str, Any],
        db: dict[str, Any],
        bulk: BulkInsightsResponse | None = None,
    ) -> None:
        super().__init__()

        daily = db["traffic_daily"]

        # Compute rolling 14d totals
        total_clones = sum(d["clones"] for d in daily)
        total_unique = sum(d["unique_cloners"] for d in daily)
        total_views = sum(d["views"] for d in daily)

        # Compute previous 14d for change arrows using bulk data (no DB)
        stars_total = db["stars_total"]

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        d14 = now - timedelta(days=14)
        d28 = now - timedelta(days=28)

        prev_clones = sum_in_range(bulk, "clones", d28, d14)
        prev_unique = sum_in_range(bulk, "unique_cloners", d28, d14)
        prev_views = sum_in_range(bulk, "views", d28, d14)

        pypi_14d = sum_in_range(bulk, "downloads_daily", d14, now + timedelta(days=1))
        pypi_prev14d = sum_in_range(bulk, "downloads_daily", d28, d14)

        # Stars in range from bulk events
        star_events = bulk.events.get("new_star", []) if bulk else []
        recent_stars = len([r for r in star_events if r.date >= d14])
        prev_star_count = len([r for r in star_events if d28 <= r.date < d14])

        insight_events = bulk.insight_events if bulk else []

        # Recent events of all types from bulk
        recent_events: list[dict[str, Any]] = []
        for ev in insight_events:
            meta = ev.metadata_ if isinstance(ev.metadata_, dict) else {}
            recent_events.append(
                {
                    "date": str(ev.date)[:10],
                    "description": ev.description,
                    "type": ev.event_type,
                    "metadata": meta,
                }
            )

        # Also add releases from bulk event metrics
        for r in bulk.events.get("releases", []) if bulk else []:
            meta = r.metadata_ or {}
            tag = meta.get("tag", "")
            if tag:
                recent_events.append(
                    {
                        "date": str(r.date)[:10],
                        "description": tag,
                        "type": "release",
                        "metadata": meta,
                    }
                )

        # Enrich reddit posts with upvote/comment data from bulk
        reddit_stats: dict[str, dict] = {}
        for r in bulk.events.get("post_stats", []) if bulk else []:
            meta = r.metadata_ or {}
            pid = meta.get("post_id", "")
            if pid:
                reddit_stats[pid] = {
                    "upvotes": int(r.value),
                    "comments": meta.get("comments", 0),
                    "subreddit": meta.get("subreddit", ""),
                }

        # Sort by date desc, take 15
        recent_events.sort(key=lambda x: x["date"], reverse=True)
        recent_events = recent_events[:15]

        # Latest day's deltas from bulk data (for "+X today/yesterday" subtitle)
        def _latest_daily(key: str) -> tuple[int, str]:
            """Get the most recent day's value and label ('today', 'yesterday', 'Xd ago')."""  # noqa: E501
            rows = bulk.daily.get(key, []) if bulk else []
            if not rows:
                return 0, "today"
            last = rows[-1]
            val = int(last.value)
            days_ago = (datetime.now() - last.date).days
            if days_ago == 0:
                return val, "today"
            if days_ago == 1:
                return val, "yesterday"
            return val, f"{days_ago}d ago"

        latest_clones, clones_label = _latest_daily("clones")
        latest_unique, unique_label = _latest_daily("unique_cloners")
        latest_views, views_label = _latest_daily("views")
        latest_downloads, dl_label = _latest_daily("downloads_daily")
        today_str = now.strftime("%Y-%m-%d")
        today_stars = len([r for r in star_events if str(r.date)[:10] == today_str])

        # Top-level metrics with change arrows + "+X today" subtitle
        metrics_row = ft.Row(
            [
                MetricCard(
                    "Stars",
                    str(stars_total),
                    "#FFD700",
                    change_pct=pct_change(recent_stars, prev_star_count),
                    prev_value=f"+{today_stars} today",
                ),
                MetricCard(
                    "PyPI Downloads",
                    f"{db['pypi_total']:,}",
                    "#FF69B4",
                    change_pct=pct_change(pypi_14d, pypi_prev14d),
                    prev_value=f"+{latest_downloads:,} {dl_label}",
                ),
                MetricCard(
                    "14d Clones",
                    f"{total_clones:,}",
                    Theme.Colors.PRIMARY,
                    change_pct=pct_change(total_clones, prev_clones),
                    prev_value=f"+{latest_clones:,} {clones_label}",
                ),
                MetricCard(
                    "14d Unique",
                    f"{total_unique:,}",
                    Theme.Colors.INFO,
                    change_pct=pct_change(total_unique, prev_unique),
                    prev_value=f"+{latest_unique:,} {unique_label}",
                ),
                MetricCard(
                    "14d Views",
                    f"{total_views:,}",
                    Theme.Colors.SUCCESS,
                    change_pct=pct_change(total_views, prev_views),
                    prev_value=f"+{latest_views:,} {views_label}",
                ),
            ],
            spacing=Theme.Spacing.MD,
        )

        # Recent activity (left) — reuse ExpandableActivityRow
        from datetime import datetime as _dt

        from app.components.frontend.controls.data_table import (
            DataTableRow,
        )
        from app.services.system.activity import ActivityEvent

        from ..activity_feed import ExpandableActivityRow

        _row_col = [DataTableColumn("Activity")]

        activity_items: list[ft.Control] = []
        for ev in recent_events:
            status = EVENT_STATUS_MAP.get(ev["type"], "info")
            try:
                ts = _dt.strptime(ev["date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                ts = _dt.now()

            # Build details from metadata
            meta = ev.get("metadata", {})
            details = None
            reddit_url = None
            if ev["type"] == "reddit_post":
                pid = meta.get("post_id", "")
                stats = reddit_stats.get(pid, {})
                parts = []
                sub = meta.get("subreddit") or stats.get("subreddit", "")
                if sub:
                    parts.append(f"r/{sub}")
                if stats.get("upvotes"):
                    parts.append(f"{stats['upvotes']} upvotes")
                if stats.get("comments"):
                    parts.append(f"{stats['comments']} comments")
                details = " \u2022 ".join(parts) if parts else None
                reddit_url = meta.get("url", "")
            elif ev["type"] == "star":
                usernames = meta.get("usernames", [])
                if usernames:
                    details = ", ".join(usernames[:10])
                    if len(usernames) > 10:
                        details += f" +{len(usernames) - 10} more"
            release_url = None
            fork_url = None
            if ev["type"] == "fork":
                actor = meta.get("actor", "")
                if actor:
                    fork_url = f"https://github.com/{actor}"
                    details = actor
            elif ev["type"] == "release":
                tag = meta.get("tag", ev["description"])
                release_url = (
                    f"https://github.com/lbedner/aegis-stack/releases/tag/{tag}"
                )
                details = tag
            elif ev["type"] in ("milestone_github", "milestone_pypi"):
                cat = meta.get("category", "")
                if cat:
                    details = cat.replace("_", " ").title()

            # For stars, show just the number in the title, name in details
            # For forks, show just "Fork" in the title, name in details
            message = ev["description"][:80]
            if ev["type"] == "star" and " \u2014 " in message:
                message = message.split(" \u2014 ")[0]  # "⭐ #99 — ncthuc" → "⭐ #99"
            elif ev["type"] == "fork" and not message.startswith("Fork #"):
                message = "Fork"

            event_obj = ActivityEvent(
                component="insights",
                event_type=ev["type"],
                message=message,
                status=status,
                timestamp=ts,
                details=details or (reddit_url if reddit_url else None),
            )
            row = ExpandableActivityRow(event_obj)
            # Hide the status dot — not needed in insights feed
            row.content.controls[0].controls[0].visible = False

            # For reddit posts, replace details with stats + clickable link
            if reddit_url and details:
                row._details_container.content = ft.Column(
                    [
                        SecondaryText(details),
                        ft.Container(
                            content=ft.Text(
                                reddit_url,
                                size=Theme.Typography.BODY_SMALL,
                                style=ft.TextStyle(
                                    color=Theme.Colors.INFO,
                                    decoration=ft.TextDecoration.UNDERLINE,
                                ),
                                selectable=False,
                            ),
                            on_click=lambda e, u=reddit_url: e.page.launch_url(u),
                            ink=True,
                        ),
                    ],
                    spacing=4,
                )
            elif fork_url:
                row._details_container.content = ft.Container(
                    content=ft.Text(
                        fork_url,
                        size=Theme.Typography.BODY_SMALL,
                        style=ft.TextStyle(
                            color=Theme.Colors.INFO,
                            decoration=ft.TextDecoration.UNDERLINE,
                        ),
                        selectable=False,
                    ),
                    on_click=lambda e, u=fork_url: e.page.launch_url(u),
                    ink=True,
                )
            elif release_url:
                row._details_container.content = ft.Container(
                    content=ft.Text(
                        release_url,
                        size=Theme.Typography.BODY_SMALL,
                        style=ft.TextStyle(
                            color=Theme.Colors.INFO,
                            decoration=ft.TextDecoration.UNDERLINE,
                        ),
                        selectable=False,
                    ),
                    on_click=lambda e, u=release_url: e.page.launch_url(u),
                    ink=True,
                )

            activity_items.append(
                DataTableRow(columns=_row_col, row_data=[row], padding=4)
            )

        # Goals (left) + Recent Activity (right) — mirrors the aegis-pulse
        # Summary layout. Goals stubbed pending the auth/no-auth/org
        # endpoint design; the old "Key Milestones" grid is gone since
        # those deltas now live on the metric cards via change_pct.
        goals_section = _build_overview_goals(bulk)

        side_by_side = ft.Row(
            [
                ft.Column([goals_section], spacing=6, expand=2),
                ft.Column(
                    [
                        H3Text("Recent Activity"),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        *activity_items,
                    ],
                    spacing=6,
                    expand=3,
                ),
            ],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Build the full OverviewView once — hero, chart series, and
        # everything else come from the same source of truth so the
        # numbers in the cards always agree with the curves below.
        overview_view = InsightViewService(bulk).overview(days=14) if bulk else None
        hero_view = overview_view.hero if overview_view else None

        # Daily Cloners chart — trim leading zero days so the curve starts
        # where collection actually picked up the project. Two series:
        # blue clones, purple unique-cloners — same palette as the GitHub
        # tab so the visual language stays consistent.
        clones_chart: LineChartCard | None = None
        if overview_view and overview_view.daily:
            trimmed = trim_leading_zeros(
                overview_view.daily, "clones", "unique_cloners"
            )
            if trimmed:
                clones_chart = LineChartCard(
                    title="Daily Cloners",
                    subtitle="unique people / clones per day",
                    x_labels=[d.date for d in trimmed],
                    series=[
                        LineSeries(
                            label="Clones",
                            color=ChartColors.TEAL,
                            points=[(i, d.clones) for i, d in enumerate(trimmed)],
                            tooltips=[f"Clones: {d.clones:,}" for d in trimmed],
                            fill=True,
                        ),
                        LineSeries(
                            label="Unique Cloners",
                            color=ChartColors.INDIGO,
                            points=[
                                (i, d.unique_cloners) for i, d in enumerate(trimmed)
                            ],
                            tooltips=[f"Unique: {d.unique_cloners:,}" for d in trimmed],
                        ),
                    ],
                )

        # Cumulative Stars chart — gold line with a 15%-opacity fill,
        # star-history style. min_y is bumped off zero so a healthy
        # project's curve doesn't get squashed against the bottom.
        stars_chart: LineChartCard | None = None
        if overview_view and overview_view.stars_daily:
            stars_daily = overview_view.stars_daily
            min_y_stars = max(
                0,
                stars_daily[0].value
                - max(1, (stars_daily[-1].value - stars_daily[0].value) // 4),
            )
            stars_chart = LineChartCard(
                title="Stars",
                subtitle="cumulative",
                x_labels=[d.date for d in stars_daily],
                series=[
                    LineSeries(
                        label="Cumulative Stars",
                        color=ChartColors.AMBER,
                        points=[(i, d.value) for i, d in enumerate(stars_daily)],
                        tooltips=[f"#{d.value:,}\n{d.date}" for d in stars_daily],
                        fill=True,
                        stroke_width=3,
                    ),
                ],
                min_y=min_y_stars,
            )

        # Daily Cloners (left, expand=2) + Stars (right, expand=1) —
        # mirrors the aegis-pulse Summary 2/3 + 1/3 split. Each side
        # collapses to nothing when its data is empty so we don't render
        # a half-empty row.
        charts_row: ft.Control | None = None
        if clones_chart and stars_chart:
            charts_row = ft.Row(
                [
                    ft.Container(content=clones_chart, expand=2),
                    ft.Container(content=stars_chart, expand=1),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        elif clones_chart:
            charts_row = clones_chart
        elif stars_chart:
            charts_row = stars_chart

        column_children: list[ft.Control] = []
        if hero_view is not None:
            column_children.append(_build_overview_hero(hero_view))
        column_children.append(metrics_row)
        if charts_row is not None:
            column_children.extend([ft.Container(height=4), charts_row])
        column_children.extend([ft.Container(height=4), side_by_side])

        self.content = ft.Column(
            column_children,
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = Theme.Spacing.MD
        self.expand = True
