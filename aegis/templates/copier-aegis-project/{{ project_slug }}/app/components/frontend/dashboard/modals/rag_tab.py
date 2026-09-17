"""
RAG Tab Component

Displays RAG service status and configuration, matching the output of
the `my-app rag status` CLI command.
"""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.surface_panel import SurfacePanel
from app.components.frontend.theme import AegisTheme as Theme

from .modal_sections import EmptyStatePlaceholder, MetricCard


def _format_timestamp(timestamp: str | None) -> str:
    """Format ISO timestamp for display."""
    if not timestamp:
        return "No activity"
    # Show date and time portion
    if "T" in timestamp:
        date_part, time_part = timestamp.split("T")
        time_part = time_part.split(".")[0]  # Remove microseconds
        return f"{date_part} {time_part}"
    return timestamp


class IndexedFileRow(ft.Container):
    """Single row showing an indexed file with chunk count."""

    def __init__(self, source: str, chunks: int) -> None:
        super().__init__()

        # Extract just the filename for display, full path on hover
        filename = source.split("/")[-1] if "/" in source else source

        self.content = ft.Row(
            [
                ft.Container(
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=14),
                    width=24,
                ),
                ft.Container(
                    BodyText(filename, tooltip=source),
                    expand=True,
                ),
                ft.Container(
                    SecondaryText(f"{chunks} chunks"),
                    width=80,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.padding = ft.padding.symmetric(
            vertical=Theme.Spacing.XS,
            horizontal=Theme.Spacing.SM,
        )


class CollectionRowCard(ft.Container):
    """Expandable card for a collection showing files on click."""

    def __init__(
        self,
        collection: dict[str, Any],
        on_load_files: Callable[[str], None],
    ) -> None:
        super().__init__()

        self.collection_name = collection.get("name", "Unknown")
        self.doc_count = collection.get("doc_count", 0)
        self.chunk_count = collection.get("chunk_count", collection.get("count", 0))
        self.on_load_files = on_load_files

        self.is_expanded = False
        self.files_loaded = False
        self.files: list[dict[str, Any]] = []

        # Expand/collapse icon
        self._icon = ft.Icon(ft.Icons.ARROW_RIGHT, size=16, color=ft.Colors.PRIMARY)

        # Loading indicator for files
        self._loading_indicator = ft.Container(
            content=ft.Row(
                [
                    ft.ProgressRing(width=16, height=16, stroke_width=2),
                    SecondaryText("Loading files..."),
                ],
                spacing=Theme.Spacing.SM,
            ),
            visible=False,
            padding=ft.padding.only(left=40, top=Theme.Spacing.SM),
        )

        # Files container (populated when expanded)
        self._files_container = ft.Container(
            visible=False,
            padding=ft.padding.only(left=40, top=Theme.Spacing.SM),
        )

        # Header row (clickable)
        self.header = ft.GestureDetector(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Container(self._icon, width=24),
                        ft.Container(
                            ft.Text(
                                self.collection_name,
                                size=13,
                                weight=ft.FontWeight.W_500,
                            ),
                            expand=True,
                        ),
                        ft.Container(
                            SecondaryText(str(self.doc_count), size=13),
                            width=60,
                            alignment=ft.alignment.center_right,
                        ),
                        ft.Container(
                            SecondaryText(str(self.chunk_count), size=13),
                            width=70,
                            alignment=ft.alignment.center_right,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                ),
                bgcolor=ft.Colors.SURFACE,
                padding=ft.padding.symmetric(horizontal=Theme.Spacing.MD, vertical=10),
                border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
            ),
            on_tap=self._toggle_expand,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        self.content = ft.Column(
            [
                self.header,
                self._loading_indicator,
                self._files_container,
            ],
            spacing=0,
        )

    def _toggle_expand(self, e: ft.ControlEvent) -> None:
        """Toggle file list expansion."""
        self.is_expanded = not self.is_expanded

        # Update icon
        self._icon.name = (
            ft.Icons.ARROW_DROP_DOWN if self.is_expanded else ft.Icons.ARROW_RIGHT
        )

        if self.is_expanded and not self.files_loaded:
            # Show loading, trigger file load
            self._loading_indicator.visible = True
            self.on_load_files(self.collection_name)
        else:
            # Just toggle visibility
            self._files_container.visible = self.is_expanded

        self.update()

    def set_files(self, files: list[dict[str, Any]]) -> None:
        """Update the files list after loading."""
        self.files = files
        self.files_loaded = True
        self._loading_indicator.visible = False

        if not files:
            self._files_container.content = ft.Container(
                content=SecondaryText("No files indexed"),
                padding=Theme.Spacing.SM,
            )
        else:
            file_rows = [IndexedFileRow(f["source"], f["chunks"]) for f in files]
            self._files_container.content = ft.ListView(
                controls=file_rows,
                spacing=0,
                height=200,
            )

        self._files_container.visible = self.is_expanded
        self.update()

    def set_error(self, message: str) -> None:
        """Show error state for file loading."""
        self.files_loaded = True
        self._loading_indicator.visible = False
        self._files_container.content = ft.Container(
            content=SecondaryText(f"Error: {message}"),
            padding=Theme.Spacing.SM,
        )
        self._files_container.visible = self.is_expanded
        self.update()


class RAGCollectionsTableSection(ft.Container):
    """Collections table with expandable rows showing file details."""

    def __init__(
        self,
        collections: list[dict[str, Any]],
        page: ft.Page,
    ) -> None:
        """
        Initialize collections table section.

        Args:
            collections: List of collection info dicts with name and count
            page: Flet page for async operations
        """
        super().__init__()

        self.page = page
        self._collection_cards: dict[str, CollectionRowCard] = {}

        if not collections:
            self.content = ft.Column(
                [
                    H3Text("Collections"),
                    ft.Container(height=Theme.Spacing.SM),
                    EmptyStatePlaceholder("No collections indexed yet"),
                ],
                spacing=0,
            )
        else:
            # Table header with muted text
            header = ft.Container(
                content=ft.Row(
                    [
                        ft.Container(width=24),  # Icon space
                        ft.Container(SecondaryText("Collection", size=12), expand=True),
                        ft.Container(
                            SecondaryText("Docs", size=12),
                            width=60,
                            alignment=ft.alignment.center_right,
                        ),
                        ft.Container(
                            SecondaryText("Chunks", size=12),
                            width=70,
                            alignment=ft.alignment.center_right,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                ),
                padding=ft.padding.symmetric(horizontal=Theme.Spacing.MD, vertical=12),
                border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
            )

            # Create expandable row cards
            rows: list[ft.Control] = []
            for collection in collections:
                card = CollectionRowCard(
                    collection=collection,
                    on_load_files=self._load_files_for_collection,
                )
                self._collection_cards[collection.get("name", "")] = card
                rows.append(card)

            # Table container with dark background
            table = SurfacePanel(
                content=ft.Column([header, *rows], spacing=0),
            )

            self.content = ft.Column(
                [
                    H3Text("Collections"),
                    ft.Container(height=Theme.Spacing.SM),
                    table,
                ],
                spacing=0,
            )
        self.padding = Theme.Spacing.MD

    def _load_files_for_collection(self, collection_name: str) -> None:
        """Trigger async file loading for a collection."""
        self.page.run_task(self._fetch_files, collection_name)

    async def _fetch_files(self, collection_name: str) -> None:
        """Fetch files for a collection from the API."""
        card = self._collection_cards.get(collection_name)
        if not card:
            return

        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(f"/api/v1/rag/collections/{collection_name}/files")
        if not isinstance(data, dict):
            card.set_error("Could not load files.")
            return
        card.set_files(data.get("files", []))


class RAGStatsSection(ft.Container):
    """Stats section showing RAG chunking and search parameters as metric cards."""

    def __init__(self, data: dict[str, Any]) -> None:
        """
        Initialize stats section.

        Args:
            data: RAG health data from API
        """
        super().__init__()

        chunk_size = data.get("chunk_size", 0)
        chunk_overlap = data.get("chunk_overlap", 0)
        default_top_k = data.get("default_top_k", 0)

        self.content = ft.Row(
            [
                MetricCard("Chunk Size", str(chunk_size), Theme.Colors.PRIMARY),
                MetricCard("Chunk Overlap", str(chunk_overlap), Theme.Colors.INFO),
                MetricCard("Default Top K", str(default_top_k), Theme.Colors.SUCCESS),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


class RAGConfigSection(ft.Container):
    """Configuration section showing RAG service settings."""

    def __init__(self, data: dict[str, Any]) -> None:
        """
        Initialize configuration section.

        Args:
            data: RAG health data from API
        """
        super().__init__()

        embedding_provider = data.get("embedding_provider", "Unknown")
        embedding_model = data.get("embedding_model", "Unknown")
        vectorstore_uri = data.get("persist_directory", "Unknown")
        last_activity = data.get("last_activity")

        def config_row(label: str, value: str) -> ft.Row:
            """Create a configuration row with label and value."""
            return ft.Row(
                [
                    SecondaryText(
                        f"{label}:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=150,
                    ),
                    BodyText(value),
                ],
                spacing=Theme.Spacing.MD,
            )

        rows = [
            config_row("Provider", embedding_provider),
            config_row("Embedding Model", embedding_model),
            config_row("Vectorstore URI", str(vectorstore_uri)),
        ]

        if last_activity:
            rows.append(config_row("Last Activity", _format_timestamp(last_activity)))

        self.content = ft.Column(rows, spacing=Theme.Spacing.XS)
        self.padding = Theme.Spacing.MD


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
