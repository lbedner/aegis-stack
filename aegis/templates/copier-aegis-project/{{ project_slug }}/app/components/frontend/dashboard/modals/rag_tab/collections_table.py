"""What is indexed: one card per collection, expanding into its files.

Files are not fetched until a collection is opened - a project with
thirty collections would otherwise make thirty requests to render a
list nobody has looked at yet - so the card is built empty and told
its files, or its error, when they arrive.
"""

from collections.abc import Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.surface_panel import SurfacePanel
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import EmptyStatePlaceholder


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
