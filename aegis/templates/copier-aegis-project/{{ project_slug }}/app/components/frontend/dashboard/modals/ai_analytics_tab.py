"""
AI Analytics Tab Component

Displays LLM usage statistics including token counts, costs, model breakdown,
and recent activity. Fetches real data from the /ai/usage/stats API endpoint.
"""

from datetime import UTC, datetime
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H3Text,
    SecondaryText,
    Tag,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.components.frontend.theme import DarkColorPalette
from app.core.formatting import format_cost, format_number

from .modal_sections import MetricCard, PieChartCard


def _format_relative_time(timestamp_str: str) -> str:
    """Convert ISO timestamp to relative time (e.g., '2 minutes ago')."""
    try:
        # Parse ISO format timestamp
        if "T" in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            return timestamp_str

        # Make timezone-aware if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        diff = now - dt

        seconds = int(diff.total_seconds())
        if seconds < 0:
            return "just now"
        elif seconds < 60:
            return f"{seconds} seconds ago" if seconds != 1 else "1 second ago"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minutes ago" if minutes != 1 else "1 minute ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hours ago" if hours != 1 else "1 hour ago"
        else:
            days = seconds // 86400
            return f"{days} days ago" if days != 1 else "1 day ago"
    except (ValueError, AttributeError):
        return timestamp_str


def _get_success_rate_color(rate: float) -> str:
    """Get color based on success rate percentage."""
    if rate >= 95:
        return Theme.Colors.SUCCESS
    elif rate >= 80:
        return ft.Colors.ORANGE
    else:
        return Theme.Colors.ERROR


def _transform_api_response(api_data: dict[str, Any]) -> dict[str, Any]:
    """Transform API response to UI-expected format.

    API field names differ slightly from what the UI components expect:
    - models[].model_id -> models[].name
    - models[].percentage -> models[].pct
    - recent_activity -> recent
    - recent_activity[].timestamp -> recent[].time (time portion only)
    """
    # Transform models
    models = []
    for m in api_data.get("models", []):
        models.append(
            {
                "name": m.get("model_id", "Unknown"),
                "vendor": m.get("vendor", "unknown"),
                "requests": m.get("requests", 0),
                "tokens": m.get("tokens", 0),
                "cost": m.get("cost", 0.0),
                "pct": m.get("percentage", 0),
            }
        )

    # Transform recent activity
    recent = []
    for r in api_data.get("recent_activity", []):
        recent.append(
            {
                "timestamp": r.get("timestamp", ""),
                "model": r.get("model", "Unknown"),
                "action": r.get("action", ""),
                "input_tokens": r.get("input_tokens", 0),
                "output_tokens": r.get("output_tokens", 0),
                "cost": r.get("cost", 0.0),
                "success": r.get("success", True),
            }
        )

    return {
        "total_tokens": api_data.get("total_tokens", 0),
        "input_tokens": api_data.get("input_tokens", 0),
        "output_tokens": api_data.get("output_tokens", 0),
        "total_cost": api_data.get("total_cost", 0.0),
        "total_requests": api_data.get("total_requests", 0),
        "success_rate": api_data.get("success_rate", 100.0),
        "models": models,
        "recent": recent,
    }


class HeroStatsSection(ft.Container):
    """Hero stats section showing key metrics in cards."""

    def __init__(self, stats: dict[str, Any]) -> None:
        """
        Initialize hero stats section.

        Args:
            stats: Dictionary with usage statistics
        """
        super().__init__()

        total_tokens = stats.get("total_tokens", 0)
        total_cost = stats.get("total_cost", 0.0)
        success_rate = stats.get("success_rate", 0.0)
        total_requests = stats.get("total_requests", 0)

        self.content = ft.Column(
            [
                ft.Row(
                    [
                        MetricCard(
                            "Total Tokens",
                            format_number(total_tokens),
                            ft.Colors.PURPLE,
                        ),
                        MetricCard(
                            "Total Cost",
                            format_cost(total_cost),
                            Theme.Colors.PRIMARY,
                        ),
                        MetricCard(
                            "Success Rate",
                            f"{success_rate:.1f}%",
                            _get_success_rate_color(success_rate),
                        ),
                        MetricCard(
                            "Requests",
                            format_number(total_requests),
                            ft.Colors.CYAN,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                ),
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


def _create_token_breakdown_card(stats: dict[str, Any]) -> PieChartCard:
    """Create token breakdown pie chart card."""
    input_tokens = stats.get("input_tokens", 0)
    output_tokens = stats.get("output_tokens", 0)
    total = input_tokens + output_tokens

    if total == 0:
        return PieChartCard("Token Breakdown", [])

    input_pct = input_tokens / total * 100
    output_pct = output_tokens / total * 100

    return PieChartCard(
        title="Token Breakdown",
        sections=[
            {
                "value": input_tokens,
                "color": DarkColorPalette.ACCENT,
                "label": f"Input Tokens ({input_pct:.1f}%)",
            },
            {
                "value": output_tokens,
                "color": ft.Colors.PURPLE_200,
                "label": f"Output Tokens ({output_pct:.1f}%)",
            },
        ],
    )


def _create_model_usage_card(stats: dict[str, Any]) -> PieChartCard:
    """Create model usage pie chart card."""
    models = stats.get("models", [])

    if not models:
        return PieChartCard("Model Usage", [])

    sections = []
    for model in models:
        pct = float(model.get("pct", 0))
        name = model.get("name", "Unknown")

        # Don't pass color - let PieChartCard auto-assign from palette
        sections.append(
            {
                "value": pct,
                "label": f"{name} ({pct:.1f}%)",
            }
        )

    return PieChartCard(title="Model Usage", sections=sections)


SENTIMENT_COLORS: dict[str, str] = {
    "positive": Theme.Colors.SUCCESS,
    "neutral": ft.Colors.BLUE_GREY_300,
    "negative": Theme.Colors.WARNING,
    "frustrated": Theme.Colors.ERROR,
}


def sentiment_chart_sections(sentiment: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a sentiment distribution to pie chart sections (non-zero only)."""
    distribution = sentiment.get("distribution", {}) or {}
    total = sum(distribution.values()) or 1
    return [
        {
            "value": count,
            "color": SENTIMENT_COLORS.get(value, ft.Colors.BLUE_GREY_300),
            "label": f"{value.title()} ({count / total * 100:.0f}%)",
        }
        for value, count in distribution.items()
        if count
    ]


class SentimentSection(ft.Container):
    """Conversation sentiment: distribution chart + recent negatives."""

    def __init__(self, sentiment: dict[str, Any]) -> None:
        super().__init__()

        chart = PieChartCard(
            title="Conversation Sentiment",
            sections=sentiment_chart_sections(sentiment),
        )

        columns = [
            DataTableColumn("Sentiment", width=110, style=None),
            DataTableColumn("Summary", width=420, style="secondary"),
            DataTableColumn("When", width=120, style="secondary"),
        ]
        rows: list[list[Any]] = []
        for row in sentiment.get("recent_negatives", []):
            value = row.get("overall_sentiment", "")
            rows.append(
                [
                    Tag(
                        text=value.title(),
                        color=SENTIMENT_COLORS.get(value, Theme.Colors.WARNING),
                    ),
                    row.get("summary") or row.get("conversation_id", ""),
                    _format_relative_time(row.get("created_at", "")),
                ]
            )

        controls: list[ft.Control] = [chart]
        if rows:
            controls.extend(
                [
                    ft.Container(height=Theme.Spacing.SM),
                    H3Text("Recent Negative Conversations"),
                    ft.Container(height=Theme.Spacing.SM),
                    DataTable(
                        columns=columns,
                        rows=rows,
                        empty_message="No negative conversations",
                    ),
                ]
            )

        self.content = ft.Column(controls, spacing=0)
        self.padding = Theme.Spacing.MD


class RecentActivitySection(ft.Container):
    """Recent activity section showing last N requests in a table."""

    def __init__(self, stats: dict[str, Any]) -> None:
        """
        Initialize recent activity section.

        Args:
            stats: Dictionary with recent activity data
        """
        super().__init__()

        recent = stats.get("recent", [])

        # Define columns with styling
        columns = [
            DataTableColumn("Time", width=120, style="secondary"),
            DataTableColumn("Model", width=140, style="primary"),
            DataTableColumn("Action", width=180, style="secondary"),
            DataTableColumn("Input", width=80, alignment="right", style="body"),
            DataTableColumn("Output", width=80, alignment="right", style="body"),
            DataTableColumn("Cost", width=90, alignment="right", style="body"),
            DataTableColumn("Status", width=80, alignment="right", style=None),
        ]

        # Build row data - strings auto-styled, Tag passed through
        rows: list[list[Any]] = []
        for activity in recent:
            success = activity.get("success", True)
            status_text = "Success" if success else "Failed"
            status_color = Theme.Colors.SUCCESS if success else Theme.Colors.ERROR
            input_tokens = activity.get("input_tokens", 0)
            output_tokens = activity.get("output_tokens", 0)
            relative_time = _format_relative_time(activity.get("timestamp", ""))

            rows.append(
                [
                    relative_time,
                    activity.get("model", ""),
                    activity.get("action", ""),
                    format_number(input_tokens),
                    format_number(output_tokens),
                    format_cost(activity.get("cost", 0)),
                    Tag(text=status_text, color=status_color),
                ]
            )

        # Build table
        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No recent activity",
        )

        self.content = ft.Column(
            [
                H3Text("Recent Activity"),
                ft.Container(height=Theme.Spacing.SM),
                table,
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


class AIAnalyticsTab(ft.Container):
    """
    Analytics tab content for the AI Service modal.

    Fetches and displays comprehensive LLM usage statistics from the API.
    Gracefully handles memory-only mode where analytics are unavailable.
    """

    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        """
        Initialize analytics tab.

        Args:
            metadata: Component metadata from health check, used to detect
                     if analytics are available (persistence != "memory")
        """
        super().__init__()

        self._metadata = metadata or {}

        # Content container that will be updated after data loads
        self._content_column = ft.Column(
            [
                ft.Container(
                    content=ft.ProgressRing(width=32, height=32),
                    alignment=ft.alignment.center,
                    padding=Theme.Spacing.XL,
                ),
                ft.Container(
                    content=SecondaryText("Loading usage statistics..."),
                    alignment=ft.alignment.center,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=Theme.Spacing.MD,
        )

        self.content = self._content_column

    def did_mount(self) -> None:
        """Called when the control is added to the page. Fetches data."""
        # Check if analytics are available (requires database backend)
        if self._metadata.get("persistence") == "memory":
            self._render_unavailable()
        else:
            self.page.run_task(self._load_stats)

    async def _load_stats(self) -> None:
        """Fetch usage stats from API and update the UI."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        api_data = await api.get("/ai/usage/stats", params={"recent_limit": 10})
        if api_data is None:
            self._render_error("Could not load usage stats.")
            return
        stats = _transform_api_response(api_data)
        # Sentiment is optional: surfaced only when conversations have
        # been scored (the job is off by default).
        sentiment = await api.get("/ai/sentiment/stats")
        self._render_stats(stats, sentiment)

    def _render_stats(
        self,
        stats: dict[str, Any],
        sentiment: dict[str, Any] | None = None,
    ) -> None:
        """Render the stats sections with loaded data."""
        # Refresh button row
        refresh_row = ft.Row(
            [
                ft.Container(expand=True),  # Spacer
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Refresh analytics",
                    on_click=self._on_refresh_click,
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
        )

        # Pie charts side by side (PieChartCard includes card styling)
        charts_row = ft.Row(
            [
                _create_token_breakdown_card(stats),
                _create_model_usage_card(stats),
            ],
            spacing=Theme.Spacing.MD,
        )

        self._content_column.controls = [
            refresh_row,
            HeroStatsSection(stats),
            ft.Container(height=Theme.Spacing.LG),  # Spacing between card rows
            charts_row,
            RecentActivitySection(stats),
        ]
        if sentiment and sentiment.get("total", 0) > 0:
            self._content_column.controls.append(SentimentSection(sentiment))
        self._content_column.scroll = ft.ScrollMode.AUTO
        self._content_column.spacing = 0
        self.update()

    def _render_error(self, message: str) -> None:
        """Render an error state."""
        self._content_column.controls = [
            ft.Container(
                content=ft.Icon(
                    ft.Icons.ERROR_OUTLINE,
                    size=48,
                    color=Theme.Colors.ERROR,
                ),
                alignment=ft.alignment.center,
                padding=Theme.Spacing.MD,
            ),
            ft.Container(
                content=H3Text("Failed to load usage statistics"),
                alignment=ft.alignment.center,
            ),
            ft.Container(
                content=SecondaryText(message),
                alignment=ft.alignment.center,
            ),
        ]
        self._content_column.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.update()

    def _render_unavailable(self) -> None:
        """Render an unavailable state when analytics require database backend."""
        self._content_column.controls = [
            ft.Container(height=40),
            ft.Icon(
                ft.Icons.ANALYTICS_OUTLINED,
                size=64,
                color=ft.Colors.OUTLINE,
            ),
            ft.Container(height=Theme.Spacing.MD),
            H3Text("Analytics Unavailable"),
            ft.Container(height=Theme.Spacing.SM),
            SecondaryText("Database backend required for usage analytics."),
            ft.Container(height=Theme.Spacing.XS),
            SecondaryText(
                'Use: uvx aegis-stack init my-app --services "ai[sqlite]"',
                italic=True,
            ),
        ]
        self._content_column.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self._content_column.alignment = ft.MainAxisAlignment.START
        self.update()

    async def _on_refresh_click(self, e: ft.ControlEvent) -> None:
        """Handle refresh button click - reload stats from API."""
        # Show loading state
        self._content_column.controls = [
            ft.Container(
                content=ft.ProgressRing(width=32, height=32),
                alignment=ft.alignment.center,
                padding=Theme.Spacing.XL,
            ),
            ft.Container(
                content=SecondaryText("Refreshing..."),
                alignment=ft.alignment.center,
            ),
        ]
        self._content_column.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self._content_column.spacing = Theme.Spacing.MD
        self.update()

        # Fetch fresh data
        await self._load_stats()
