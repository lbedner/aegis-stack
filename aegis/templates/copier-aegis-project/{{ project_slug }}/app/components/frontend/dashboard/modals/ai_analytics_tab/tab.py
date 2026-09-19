"""The tab itself: fetch, transform, lay the sections out."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from .activity import RecentActivitySection
from .sentiment import SentimentSection
from .shaping import _transform_api_response
from .stats import (
    HeroStatsSection,
    _create_model_usage_card,
    _create_token_breakdown_card,
)


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
        api_data = await api.get("/api/v1/ai/usage/stats", params={"recent_limit": 10})
        if api_data is None:
            self._render_error("Could not load usage stats.")
            return
        stats = _transform_api_response(api_data)
        # Sentiment is optional: surfaced only when conversations have
        # been scored (the job is off by default).
        sentiment = await api.get("/api/v1/ai/sentiment/stats")
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
