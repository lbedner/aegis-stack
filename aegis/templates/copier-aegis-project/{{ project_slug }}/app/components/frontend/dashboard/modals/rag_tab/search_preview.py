"""Ask the index a question and see what comes back.

The one part of this tab that writes to the service. A result card
shows the chunk that matched and where it came from, because a
retrieval that looks right for the wrong reason is the failure worth
catching here.
"""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
    Tag,
)
from app.components.frontend.theme import AegisTheme as Theme


class SearchResultCard(ft.Container):
    """Display a single search result."""

    def __init__(self, result: dict[str, Any], rank: int) -> None:
        super().__init__()

        content = result.get("content", "")
        metadata = result.get("metadata", {})
        score = result.get("score", 0.0)
        source = metadata.get("source", "Unknown")

        # Extract chunk metadata
        chunk_index = metadata.get("chunk_index", 0)
        total_chunks = metadata.get("total_chunks", 1)
        chunk_size = metadata.get("chunk_size", len(content))
        start_line = metadata.get("start_line")
        end_line = metadata.get("end_line")

        # Truncate content for display
        max_content_len = 150
        display_content = (
            content[:max_content_len] + "..."
            if len(content) > max_content_len
            else content
        )

        # Extract filename from source
        filename = source.split("/")[-1] if "/" in source else source

        # Score color based on relevance
        score_pct = int(score * 100)
        score_color = (
            Theme.Colors.SUCCESS
            if score_pct >= 70
            else Theme.Colors.WARNING
            if score_pct >= 40
            else Theme.Colors.ERROR
        )

        # Build info items for header
        info_items: list[ft.Control] = [
            ft.Text(f"#{rank}", size=12, weight=ft.FontWeight.W_600),
            ft.Container(
                SecondaryText(filename, tooltip=source, size=12),
                expand=True,
            ),
        ]

        # Add chunk position (e.g., "2/5")
        info_items.append(SecondaryText(f"{chunk_index + 1}/{total_chunks}", size=10))

        # Add line range if available
        if start_line and end_line:
            info_items.append(SecondaryText(f"L{start_line}-{end_line}", size=10))

        # Add chunk size
        info_items.append(SecondaryText(f"{chunk_size} chars", size=10))

        # Add score tag
        info_items.append(Tag(text=f"{score_pct}%", color=score_color))

        # Header row with table-like styling
        header = ft.Container(
            content=ft.Row(info_items, spacing=Theme.Spacing.SM),
            bgcolor=ft.Colors.SURFACE,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.SM, vertical=8),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
        )

        # Content preview with smaller text
        content_section = ft.Container(
            content=ft.Text(
                display_content, size=11, color=ft.Colors.ON_SURFACE_VARIANT
            ),
            padding=Theme.Spacing.SM,
        )

        self.content = ft.Column([header, content_section], spacing=0)
        self.bgcolor = ft.Colors.SURFACE
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        self.expand = True


class SearchPreviewSection(ft.Container):
    """Search preview panel for testing semantic search."""

    def __init__(self, collections: list[str], page: ft.Page) -> None:
        super().__init__()

        self.page = page
        self.collections = collections

        # Search input
        self._search_input = ft.TextField(
            hint_text="Enter search query...",
            expand=True,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=ft.Colors.PRIMARY,
            cursor_color=ft.Colors.PRIMARY,
            text_size=13,
            on_submit=self._on_search_submit,
        )

        # Collection dropdown
        self._collection_dropdown = ft.Dropdown(
            label="Collection",
            options=[ft.dropdown.Option(c) for c in collections],
            value=collections[0] if collections else None,
            width=200,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=ft.Colors.PRIMARY,
            text_size=13,
        )

        # Search button
        self._search_button = ft.OutlinedButton(
            text="Search",
            icon=ft.Icons.SEARCH,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            style=ft.ButtonStyle(
                color=ft.Colors.ON_SURFACE_VARIANT,
                side=ft.BorderSide(1, ft.Colors.ON_SURFACE_VARIANT),
                shape=ft.RoundedRectangleBorder(radius=Theme.Components.INPUT_RADIUS),
            ),
            on_click=self._on_search_click,
        )

        # Results container
        self._results_container = ft.Column(
            [],
            spacing=Theme.Spacing.SM,
        )

        # Status text
        self._status_text = ft.Container(
            content=SecondaryText("Enter a query to search"),
            visible=True,
        )

        # Loading indicator
        self._loading = ft.Container(
            content=ft.Row(
                [
                    ft.ProgressRing(width=20, height=20, stroke_width=2),
                    SecondaryText("Searching..."),
                ],
                spacing=Theme.Spacing.SM,
            ),
            visible=False,
        )

        # Build layout
        search_row = ft.Row(
            [
                self._search_input,
                self._collection_dropdown,
                self._search_button,
            ],
            spacing=Theme.Spacing.SM,
        )

        self.content = ft.Column(
            [
                H3Text("Search Preview"),
                ft.Container(height=Theme.Spacing.SM),
                search_row,
                ft.Container(height=Theme.Spacing.SM),
                self._loading,
                self._status_text,
                self._results_container,
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD

    async def _on_search_submit(self, e: ft.ControlEvent) -> None:
        """Handle Enter key in search field."""
        await self._do_search()

    async def _on_search_click(self, e: ft.ControlEvent) -> None:
        """Handle search button click."""
        await self._do_search()

    async def _do_search(self) -> None:
        """Trigger the search."""
        query = self._search_input.value
        collection = self._collection_dropdown.value

        if not query or not query.strip():
            self._show_status("Please enter a search query")
            return

        if not collection:
            self._show_status("Please select a collection")
            return

        await self._execute_search(query.strip(), collection)

    def _show_status(self, message: str) -> None:
        """Show a status message."""
        self._status_text.content = SecondaryText(message)
        self._status_text.visible = True
        self._results_container.controls = []
        self.update()

    def _show_loading(self) -> None:
        """Show loading state."""
        self._loading.visible = True
        self._status_text.visible = False
        self._results_container.controls = []
        self.update()

    async def _execute_search(self, query: str, collection: str) -> None:
        """Execute semantic search via API."""
        from app.components.frontend.state.session_state import get_session_state

        self._show_loading()
        api = get_session_state(self.page).api_client
        data = await api.post(
            "/api/v1/rag/search",
            json={"query": query, "collection_name": collection, "top_k": 5},
        )
        self._loading.visible = False
        if not isinstance(data, dict):
            self._show_status("Search failed.")
            return
        results = data.get("results", [])
        if not results:
            self._show_status("No results found")
        else:
            self._display_results(results)

    def _display_results(self, results: list[dict[str, Any]]) -> None:
        """Display search results in 2-column grid."""
        self._status_text.visible = False

        # Create cards and arrange in rows of 2
        cards = [
            SearchResultCard(result, result.get("rank", i + 1))
            for i, result in enumerate(results)
        ]

        rows: list[ft.Control] = []
        for i in range(0, len(cards), 2):
            row_cards = cards[i : i + 2]
            rows.append(ft.Row(row_cards, spacing=Theme.Spacing.MD))

        self._results_container.controls = rows
        self.update()
