"""The Cloud Catalog tab: the four sections, stacked."""

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from .featured import (
    FEATURED_VENDORS,
    FeaturedModelsSection,
)
from .search import ModelSearchSection
from .sections import ActiveModelSection, CatalogStatsSection


class LLMCatalogTab(ft.Container):
    """
    LLM Catalog tab content for the AI Service modal.

    Fetches and displays LLM catalog information including stats,
    vendors, and searchable model list.
    """

    def __init__(self) -> None:
        super().__init__()

        self._content_column = ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.ProgressBar(),
                            SecondaryText("Loading LLM catalog..."),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.MD,
                    ),
                    padding=Theme.Spacing.XL,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )

        self.content = self._content_column

    def did_mount(self) -> None:
        """Called when the control is added to the page."""
        self.page.run_task(self._load_data)

    async def _load_data(self) -> None:
        """Fetch all data from API and update UI."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client

        # Fan out: stats + vendors + modalities + featured-vendor models.
        results = await asyncio.gather(
            api.get("/api/v1/llm/status"),
            api.get("/api/v1/llm/vendors"),
            api.get("/api/v1/llm/modalities"),
            api.get("/api/v1/llm/current"),
            *[
                api.get(
                    "/api/v1/llm/models",
                    params={"vendor": vendor, "limit": 15},
                )
                for vendor in FEATURED_VENDORS
            ],
            return_exceptions=True,
        )

        stats_resp, vendors_resp, modalities_resp, current_resp = results[:4]
        featured_responses = results[4:]

        stats = stats_resp if isinstance(stats_resp, dict) else {}
        vendors = vendors_resp if isinstance(vendors_resp, list) else []
        modalities = modalities_resp if isinstance(modalities_resp, list) else []
        current = current_resp if isinstance(current_resp, dict) else {}

        featured_models: dict[str, list[dict[str, Any]]] = {}
        for i, vendor in enumerate(FEATURED_VENDORS):
            resp = featured_responses[i]
            featured_models[vendor] = resp if isinstance(resp, list) else []

        self._render_content(stats, vendors, modalities, featured_models, current)

    def _render_content(
        self,
        stats: dict[str, Any],
        vendors: list[dict[str, Any]],
        modalities: list[dict[str, Any]],
        featured_models: dict[str, list[dict[str, Any]]],
        current: dict[str, Any],
    ) -> None:
        """Render the content sections with loaded data."""
        # Extract vendor/modality names for dropdowns
        vendor_names = [v.get("name", "") for v in vendors]
        modality_names = [m.get("modality", "") for m in modalities]

        # Refresh button
        refresh_row = ft.Row(
            [
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Refresh catalog",
                    on_click=self._on_refresh_click,
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
        )

        self._content_column.controls = [
            refresh_row,
            ActiveModelSection(current, page=self.page, on_reset=self._load_data),
            CatalogStatsSection(stats),
            ModelSearchSection(
                vendor_names,
                modality_names,
                self.page,
                on_switched=self._load_data,
            ),
            ft.Divider(height=20, color=ft.Colors.OUTLINE),
            FeaturedModelsSection(featured_models),
        ]
        self._content_column.scroll = ft.ScrollMode.AUTO
        self._content_column.spacing = 0
        self.update()

    def _render_error(self, message: str) -> None:
        """Render an error state."""
        self._content_column.controls = [
            ft.Container(
                content=ft.Icon(
                    ft.Icons.ERROR_OUTLINE, size=48, color=Theme.Colors.ERROR
                ),
                alignment=ft.alignment.center,
                padding=Theme.Spacing.MD,
            ),
            ft.Container(
                content=H3Text("Failed to load LLM catalog"),
                alignment=ft.alignment.center,
            ),
            ft.Container(
                content=SecondaryText(message),
                alignment=ft.alignment.center,
            ),
        ]
        self._content_column.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.update()

    async def _on_refresh_click(self, e: ft.ControlEvent) -> None:
        """Handle refresh button click - reload data from API."""
        # Show loading state
        self._content_column.controls = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.ProgressBar(),
                        SecondaryText("Refreshing..."),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.MD,
                ),
                padding=Theme.Spacing.XL,
            ),
        ]
        self._content_column.spacing = Theme.Spacing.MD
        self.update()

        await self._load_data()
