"""The RAG tab: status on mount, then the four sections it feeds.

Matches the output of the ``rag status`` CLI command. Everything below
it is rebuilt from one status fetch, so a refresh is one request and
not four.
"""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from .collections_table import RAGCollectionsTableSection
from .panels import RAGConfigSection, RAGStatsSection
from .search_preview import SearchPreviewSection


class RAGTab(ft.Container):
    """
    RAG tab content for the AI Service modal.

    Fetches and displays RAG service status matching the CLI `rag status` command.
    """

    def __init__(self) -> None:
        """Initialize RAG tab."""
        super().__init__()

        # Content container that will be updated after data loads
        self._content_column = ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.ProgressBar(),
                            SecondaryText("Loading RAG status..."),
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
        """Called when the control is added to the page. Fetches data."""
        self.page.run_task(self._load_status)

    async def _load_status(self) -> None:
        """Fetch RAG status from API and update the UI."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client

        health_data = await api.get("/api/v1/rag/health")
        if not isinstance(health_data, dict):
            self._render_error("Could not load RAG health.")
            return

        collection_names = await api.get("/api/v1/rag/collections")
        collections: list[dict[str, Any]] = []
        if isinstance(collection_names, list):
            for name in collection_names:
                detail = await api.get(f"/api/v1/rag/collections/{name}")
                if isinstance(detail, dict):
                    collections.append(
                        {
                            "name": detail.get("name", name),
                            "doc_count": detail.get("doc_count", 0),
                            "chunk_count": detail.get("count", 0),
                        }
                    )
                else:
                    collections.append(
                        {"name": name, "doc_count": "?", "chunk_count": "?"}
                    )

        self._render_status(health_data, collections)

    def _render_status(
        self, data: dict[str, Any], collections: list[dict[str, Any]]
    ) -> None:
        """Render the status sections with loaded data."""
        # Refresh button row
        refresh_row = ft.Row(
            [
                ft.Container(expand=True),  # Spacer
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Refresh RAG status",
                    on_click=self._on_refresh_click,
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
        )

        # Extract collection names for search dropdown
        collection_names = [c.get("name", "") for c in collections if c.get("name")]

        sections: list[ft.Control] = [
            refresh_row,
            RAGStatsSection(data),
            RAGConfigSection(data),
            RAGCollectionsTableSection(collections, self.page),
        ]

        # Add search preview if there are collections
        if collection_names:
            sections.append(SearchPreviewSection(collection_names, self.page))

        self._content_column.controls = sections
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
                content=H3Text("Failed to load RAG status"),
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
        """Handle refresh button click - reload status from API."""
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

        # Fetch fresh data
        await self._load_status()
