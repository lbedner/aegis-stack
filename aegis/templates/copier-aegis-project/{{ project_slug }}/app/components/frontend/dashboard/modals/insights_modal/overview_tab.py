"""The Overview tab: hero numbers, goals, and the activity feed."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DisplayText,
    ErrorText,
    H3Text,
    LabelText,
    SecondaryText,
    SuccessText,
)
from app.components.frontend.controls.data_table import (
    DataTableColumn,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.schemas.views import OverviewHero
from app.services.insights.views import InsightViewService
from app.services.insights.views.formatting import pct as pct_change

from ..modal_sections import (
    ChartColors,
    LineChartCard,
    LineSeries,
    MetricCard,
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


def _format_hero_number(n: float) -> str:
    """One decimal when fractional, no trailing '.0' on whole numbers."""
    if n is None:
        return "—"
    if float(n).is_integer():
        return str(int(n))
    return f"{n:.1f}"


def _build_overview_hero(hero: OverviewHero) -> ft.Container:
    """Editorial 'king metric' card: avg daily unique cloners.

    Mirrors the aegis-pulse Summary hero block — big number on the left,
    prior-period delta on the right, footer with totals. Renders only the
    delta block when ``change_pct`` is present (no prior data → no arrow).
    Uses Aegis text controls so the typography stays consistent with the
    rest of the dashboard.
    """
    # Subtitle: "people / day, last N days" or "all time" for huge ranges.
    if hero.range_days >= 9000:
        subtitle = "people / day, all time"
    else:
        subtitle = f"people / day, last {hero.range_days} days"

    # Hero number is intentionally larger than DisplayText (32) — it has
    # to dominate the card visually. Hand-set size; weight comes from the
    # control's defaults so we keep the family/selectable behavior.
    big_number = DisplayText(
        _format_hero_number(hero.avg_daily_unique_cloners),
        size=64,
        weight=Theme.Typography.WEIGHT_SEMIBOLD,
    )

    # Footer mixes emphasized numbers with muted descriptors. BodyText
    # for the numbers (default weight regular) bumped to medium for
    # readability; SecondaryText carries the muted units.
    footer_pieces: list[ft.Control] = [
        BodyText(
            f"{hero.total_unique_cloners:,}",
            size=Theme.Typography.BODY_SMALL,
            weight=Theme.Typography.WEIGHT_MEDIUM,
        ),
        SecondaryText(" total uniques", size=Theme.Typography.BODY_SMALL),
        SecondaryText(" · ", size=Theme.Typography.BODY_SMALL),
        BodyText(
            f"{hero.total_clones:,}",
            size=Theme.Typography.BODY_SMALL,
            weight=Theme.Typography.WEIGHT_MEDIUM,
        ),
        SecondaryText(" clones", size=Theme.Typography.BODY_SMALL),
        SecondaryText(" · ", size=Theme.Typography.BODY_SMALL),
        BodyText(
            f"{hero.avg_daily_clones:.1f}",
            size=Theme.Typography.BODY_SMALL,
            weight=Theme.Typography.WEIGHT_MEDIUM,
        ),
        SecondaryText(" clones / day avg", size=Theme.Typography.BODY_SMALL),
    ]

    left_block = ft.Column(
        [
            LabelText(
                "AVG DAILY UNIQUE CLONERS",
                color=Theme.Colors.PRIMARY,
            ),
            ft.Row(
                [
                    big_number,
                    SecondaryText(subtitle),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.END,
                wrap=True,
            ),
            ft.Row(footer_pieces, spacing=0, wrap=True),
        ],
        spacing=8,
        expand=True,
    )

    row_children: list[ft.Control] = [left_block]

    # Right-side prior-period delta — only shown when we have a comparison.
    if hero.change_pct is not None:
        is_down = hero.change_pct < 0
        # SuccessText / ErrorText carry the right semantic color; size
        # bumped to H2 so the delta reads at a glance from across the card.
        delta_arrow = "▼" if is_down else "▲"
        delta_text = f"{delta_arrow} {abs(hero.change_pct)}%"
        delta_control: ft.Control = (
            ErrorText(
                delta_text,
                size=Theme.Typography.H2,
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
            )
            if is_down
            else SuccessText(
                delta_text,
                size=Theme.Typography.H2,
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
            )
        )
        right_block = ft.Column(
            [
                LabelText("VS PRIOR PERIOD"),
                delta_control,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.END,
            spacing=4,
        )
        row_children.append(right_block)

    # Match MetricCard: same bgcolor, border weight/color, and corner
    # radius so the hero reads as part of the same visual family rather
    # than a foreign panel above it.
    return ft.Container(
        content=ft.Row(
            row_children,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=Theme.Spacing.LG,
        ),
        padding=Theme.Spacing.LG,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.border.all(0.5, ft.Colors.OUTLINE),
        border_radius=Theme.Components.CARD_RADIUS,
        margin=ft.margin.only(bottom=Theme.Spacing.MD),
    )


def _build_overview_goals(bulk: BulkInsightsResponse | None) -> ft.Column:
    """Stubbed Goals section.

    Goals are auth-gated in the templates (the real `Goal` model carries a
    `user_id` FK), so projects generated without auth don't have
    persistent goals yet. Until the auth/no-auth/org endpoint design is
    settled, this builds four placeholder goals from the live current
    values in ``bulk`` and synthetic targets — the UI shape is real, the
    targets aren't. Replace the body with real `Goal` rows when the
    Goal API endpoint is wired through.
    """
    header = H3Text("Goals")
    divider = ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT)

    if bulk is None:
        return ft.Column(
            [header, divider, SecondaryText("No data yet.")],
            spacing=6,
        )

    # Pull real current values from bulk so the cards aren't lying about
    # where the project actually stands — only the targets are synthetic.
    star_count = len(bulk.events.get("new_star", []))
    pypi_total_row = bulk.latest.get("downloads_total")
    pypi_total = int(pypi_total_row.value) if pypi_total_row else 0
    clones_total = sum(int(r.value) for r in bulk.daily.get("clones", []))
    unique_cloners_total = sum(
        int(r.value) for r in bulk.daily.get("unique_cloners", [])
    )

    # Two cards above current (in-progress feel), two below (achieved
    # / over-target feel) so the visual mix shows both states.
    fake_goals: list[tuple[str, int, int]] = [
        ("Pypi — Downloads", pypi_total, max(35_000, pypi_total * 2)),
        ("Github — Stars", star_count, max(150, int(star_count * 1.5))),
        ("Github — Clones", clones_total, max(2_500, int(clones_total * 0.85))),
        (
            "Github — Unique Cloners",
            unique_cloners_total,
            max(500, int(unique_cloners_total * 0.75)),
        ),
    ]

    rows: list[ft.Control] = []
    for label, current, target in fake_goals:
        pct_raw = (current / target * 100) if target > 0 else 0
        achieved = pct_raw >= 100
        pct = int(pct_raw)

        top_row = ft.Row(
            [
                BodyText(label, weight=Theme.Typography.WEIGHT_MEDIUM),
                ft.Row(
                    [
                        BodyText(
                            f"{current:,}",
                            size=Theme.Typography.BODY_SMALL,
                            weight=Theme.Typography.WEIGHT_MEDIUM,
                        ),
                        SecondaryText(
                            f" / {target:,}", size=Theme.Typography.BODY_SMALL
                        ),
                    ],
                    spacing=0,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        bar = ft.ProgressBar(
            # `value` clamped to 1.0 — flet renders >1 as overflow.
            value=min(pct_raw / 100, 1.0),
            color=Theme.Colors.SUCCESS if achieved else Theme.Colors.PRIMARY,
            bgcolor=Theme.Colors.SURFACE_2,
            height=6,
            border_radius=3,
        )

        bottom = SecondaryText(f"{pct}%", size=Theme.Typography.BODY_SMALL)

        rows.append(ft.Column([top_row, bar, bottom], spacing=4))

    # Match MetricCard styling so this reads as the same family of
    # surfaces as the metric row above.
    card = ft.Container(
        content=ft.Column(rows, spacing=Theme.Spacing.SM),
        padding=Theme.Spacing.MD,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.border.all(0.5, ft.Colors.OUTLINE),
        border_radius=Theme.Components.CARD_RADIUS,
    )

    return ft.Column([header, divider, card], spacing=6)


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
        from datetime import datetime, timedelta

        stars_total = db["stars_total"]

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        d14 = now - timedelta(days=14)
        d28 = now - timedelta(days=28)

        def _sum_bulk_range(key: str, start: datetime, end: datetime) -> int:
            rows = bulk.daily.get(key, []) if bulk else []
            return sum(int(r.value) for r in rows if start <= r.date < end)

        prev_clones = _sum_bulk_range("clones", d28, d14)
        prev_unique = _sum_bulk_range("unique_cloners", d28, d14)
        prev_views = _sum_bulk_range("views", d28, d14)

        pypi_14d = _sum_bulk_range("downloads_daily", d14, now + timedelta(days=1))
        pypi_prev14d = _sum_bulk_range("downloads_daily", d28, d14)

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
            trimmed = overview_view.daily
            for i, d in enumerate(overview_view.daily):
                if d.clones or d.unique_cloners:
                    trimmed = overview_view.daily[i:]
                    break
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
