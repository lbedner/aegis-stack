"""The Reddit mentions tab."""

from __future__ import annotations  # noqa: I001


import flet as ft

from app.components.frontend.controls import (
    BodyText,
    LabelText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.schemas import BulkInsightsResponse

from app.components.frontend.dashboard.modals.insights_modal.charts import (
    _pretty_date,
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


class RedditTab(ft.Container):
    """Reddit: tracked post stats from database."""

    def __init__(self, bulk: BulkInsightsResponse | None = None) -> None:
        super().__init__()
        self._bulk = bulk

        posts = self._load_posts()

        if not posts:
            self.content = ft.Column(
                [
                    SecondaryText(
                        "No Reddit posts tracked. Use: my-app insights reddit add <url>"
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            )
            self.padding = Theme.Spacing.MD
            self.expand = True
            return

        last_date = posts[0]["date"] if posts else ""
        content: list[ft.Control] = [
            SecondaryText(
                f"Last updated: {last_date}" if last_date else "",
                size=Theme.Typography.BODY_SMALL,
            ),
            ft.Container(height=4),
        ]

        for post in posts:
            meta = post.get("metadata", {})
            subreddit = meta.get("subreddit", "")
            title = meta.get("title", "")
            comments = meta.get("comments", 0)
            upvote_ratio = meta.get("upvote_ratio", 0)
            url = meta.get("url", "")
            upvotes = post.get("upvotes", 0)
            date = post.get("date", "")

            # Post card — compact layout
            post_card = ft.Container(
                content=ft.Column(
                    [
                        # Row 1: subreddit + date + stats
                        ft.Row(
                            [
                                ft.Container(
                                    content=LabelText(
                                        f"r/{subreddit}", color=Theme.Colors.BADGE_TEXT
                                    ),
                                    bgcolor="#FF5722",
                                    padding=ft.padding.symmetric(
                                        horizontal=6, vertical=2
                                    ),
                                    border_radius=4,
                                ),
                                SecondaryText(
                                    _pretty_date(date), size=Theme.Typography.BODY_SMALL
                                ),
                                ft.Container(expand=True),
                                ft.Text(
                                    f"{upvotes:,}",
                                    size=13,
                                    weight=ft.FontWeight.W_700,
                                    color="#FF5722",
                                ),
                                SecondaryText("upvotes", size=Theme.Typography.CAPTION),
                                ft.Container(width=8),
                                ft.Text(
                                    str(comments),
                                    size=13,
                                    weight=ft.FontWeight.W_700,
                                    color=Theme.Colors.INFO,
                                ),
                                SecondaryText(
                                    "comments", size=Theme.Typography.CAPTION
                                ),
                                ft.Container(width=8),
                                ft.Text(
                                    f"{upvote_ratio:.0%}",
                                    size=13,
                                    weight=ft.FontWeight.W_700,
                                    color=Theme.Colors.SUCCESS
                                    if upvote_ratio and upvote_ratio > 0.9
                                    else Theme.Colors.WARNING,
                                ),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        # Row 2: title as hyperlink
                        ft.Text(
                            spans=[
                                ft.TextSpan(
                                    title,
                                    style=ft.TextStyle(
                                        size=13,
                                        decoration=ft.TextDecoration.UNDERLINE,
                                        color=Theme.Colors.PRIMARY,
                                    ),
                                    url=url,
                                ),
                            ],
                        )
                        if url
                        else BodyText(title),
                    ],
                    spacing=6,
                ),
                padding=ft.padding.all(10),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
            )

            content.append(post_card)

        self.content = ft.Column(
            content,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = Theme.Spacing.MD
        self.expand = True

    def _load_posts(self) -> list[dict]:
        """Load Reddit posts from bulk pre-loaded data."""
        rows = self._bulk.events.get("post_stats", [])
        if not rows:
            return []

        # Get original post dates from events
        event_dates: dict[str, str] = {}
        for ev in [
            ev for ev in self._bulk.insight_events if ev.event_type in {"reddit_post"}
        ]:
            pid = (ev.metadata_ or {}).get("post_id", "")
            if pid and pid not in event_dates:
                event_dates[pid] = str(ev.date)[:10]

        # Group by post_id, take latest snapshot per post
        seen: set[str] = set()
        posts = []
        for r in rows:
            meta = r.metadata_ or {}
            post_id = meta.get("post_id", "")
            if post_id in seen:
                continue
            seen.add(post_id)
            original_date = event_dates.get(post_id, str(r.date)[:10])
            posts.append(
                {
                    "upvotes": int(r.value),
                    "date": original_date,
                    "metadata": meta,
                }
            )

        return posts
