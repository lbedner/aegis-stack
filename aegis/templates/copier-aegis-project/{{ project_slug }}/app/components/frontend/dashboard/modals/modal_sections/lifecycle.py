"""The lifecycle flow: stages, connectors, and the inspector behind them."""

from __future__ import annotations

import contextlib  # noqa: I001

import flet as ft
from app.components.frontend.controls import (
    H3Text,
    LabelText,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme


class FlowConnector(ft.Container):
    """Vertical connector with arrow between flow sections."""

    def __init__(self) -> None:
        """Initialize flow connector."""
        super().__init__()
        self.content = ft.Column(
            [
                # Vertical line (thicker)
                ft.Container(
                    width=3,
                    height=30,
                    bgcolor=Theme.Colors.BORDER_DEFAULT,
                    border_radius=2,
                ),
                # Arrow icon
                ft.Icon(
                    ft.Icons.ARROW_DROP_DOWN,
                    size=20,
                    color=Theme.Colors.BORDER_DEFAULT,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.XS)


class LifecycleInspector(ft.Container):
    """Right-side inspector panel showing selected card details."""

    def __init__(self) -> None:
        """Initialize lifecycle inspector panel."""
        super().__init__()
        self._selected_card: LifecycleCard | None = None
        self._name_text = PrimaryText("")
        self._subtitle_text = SecondaryText("")
        self._badge_container = ft.Container(visible=False)
        self._details_column: ft.Column = ft.Column([], spacing=8)
        self._showing_empty_state = True

        # Main column that will swap between empty state and content
        self._main_column = ft.Column(
            [
                ft.Icon(
                    ft.Icons.TOUCH_APP, size=48, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                SecondaryText("Select a lifecycle hook"),
                SecondaryText("to inspect configuration", size=12),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.content = self._main_column
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.width = 300

    def clear_selection(self) -> None:
        """Reset inspector to empty state (e.g., on queue switch)."""
        if self._selected_card:
            with contextlib.suppress(Exception):
                self._selected_card.set_selected(False)
            self._selected_card = None

    def select_card(self, card: LifecycleCard) -> None:  # noqa: F821
        """Select a card and update inspector."""
        # Deselect previous (guard against unmounted cards)
        if self._selected_card:
            with contextlib.suppress(Exception):
                self._selected_card.set_selected(False)
        # Select new
        self._selected_card = card
        card.set_selected(True)
        # Show details
        self.show_details(
            card.name,
            card.subtitle,
            card._details,
            card._badge_text,
            card._badge_color,
            card.section,
        )

    def _create_code_block(self, text: str, copyable: bool = False) -> ft.Container:
        """Create styled code block for values."""
        content_items: list[ft.Control] = [
            ft.Text(
                text,
                font_family="monospace",
                size=12,
                color=ft.Colors.ON_SURFACE_VARIANT,
                selectable=True,
                expand=True,
            ),
        ]
        if copyable:
            content_items.append(
                ft.IconButton(
                    icon=ft.Icons.COPY,
                    icon_size=14,
                    tooltip="Copy",
                    on_click=lambda e: self._copy_to_clipboard(text),
                ),
            )
        return ft.Container(
            content=ft.Row(content_items, spacing=4),
            bgcolor=ft.Colors.SURFACE,
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
        )

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard with feedback."""
        if self.page:
            self.page.set_clipboard(text)
            self.page.open(ft.SnackBar(content=ft.Text("Copied to clipboard")))

    def show_details(
        self,
        name: str,
        subtitle: str,
        details: dict[str, object],
        badge_text: str | None = None,
        badge_color: str | None = None,
        section: str = "",
    ) -> None:
        """
        Update inspector with card data.

        Args:
            name: Card name to display
            subtitle: Card subtitle to display
            details: Dict of key-value pairs to show
            badge_text: Optional badge text (e.g., "Security")
            badge_color: Badge background color
            section: Section name for context header
        """
        self._name_text.value = name
        self._subtitle_text.value = subtitle

        # Update badge
        if badge_text:
            self._badge_container.content = LabelText(
                badge_text, color=Theme.Colors.BADGE_TEXT
            )
            self._badge_container.padding = ft.padding.symmetric(
                horizontal=6, vertical=2
            )
            self._badge_container.bgcolor = badge_color or ft.Colors.AMBER
            self._badge_container.border_radius = 4
            self._badge_container.visible = True
        else:
            self._badge_container.visible = False

        # Build details (skip Module - already shown as subtitle)
        detail_rows: list[ft.Control] = []
        for key, value in details.items():
            if key == "Module":
                continue

            detail_rows.append(SecondaryText(f"{key}:"))

            # Handle lists - join items with newlines in one block
            if isinstance(value, list):
                list_text = ",\n".join(str(item) for item in value)
                detail_rows.append(self._create_code_block(list_text))
            else:
                detail_rows.append(self._create_code_block(str(value)))

        self._details_column.controls = detail_rows

        # Build content with optional section header
        content_controls: list[ft.Control] = []

        # Section context header (e.g., "Startup Hooks")
        if section:
            content_controls.append(SecondaryText(section))

        # Card name + badge
        content_controls.append(
            ft.Row(
                [self._name_text, self._badge_container],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        content_controls.append(self._subtitle_text)
        content_controls.append(ft.Divider())
        content_controls.append(self._details_column)

        # Swap to content view
        self._main_column.controls = content_controls
        self._main_column.horizontal_alignment = ft.CrossAxisAlignment.START
        self._main_column.spacing = Theme.Spacing.SM
        self._showing_empty_state = False
        self.update()


class LifecycleCard(ft.Container):
    """Clickable card for lifecycle items (hooks or middleware)."""

    def __init__(
        self,
        name: str,
        subtitle: str,
        section: str = "",
        details: dict[str, object] | None = None,
        badge: str | None = None,
        badge_color: str | None = None,
        inspector: LifecycleInspector | None = None,
    ) -> None:
        """
        Initialize lifecycle card.

        Args:
            name: Function/class name (e.g., database_init, CORSMiddleware)
            subtitle: Module path for inspector
            section: Section name (e.g., "Startup Hooks") for inspector context
            details: Optional dict of key-value pairs for inspector view
            badge: Optional badge text (e.g., "Security")
            badge_color: Badge background color
            inspector: Shared inspector panel to update on click
        """
        super().__init__()
        # Auto-format: snake_case -> Title Case, preserve CamelCase
        if "_" in name:
            display_name = name.replace("_", " ").title()
        elif name.islower():
            display_name = name.capitalize()
        else:
            display_name = name  # Preserve CamelCase
        self.name = display_name
        self.subtitle = subtitle
        self.section = section
        self._raw_name = name  # Keep original for code reference
        self._details = details or {}
        self._badge_text = badge
        self._badge_color = badge_color or ft.Colors.AMBER
        self._inspector = inspector
        self._is_selected = False

        # Build card header: Title + Badge on top, code name below
        header_row_content: list[ft.Control] = [PrimaryText(display_name)]

        # Add badge if provided
        if self._badge_text:
            header_row_content.append(
                ft.Container(
                    content=LabelText(self._badge_text, color=Theme.Colors.BADGE_TEXT),
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    bgcolor=self._badge_color,
                    border_radius=4,
                    margin=ft.margin.only(left=Theme.Spacing.SM),
                )
            )

        self.card_header = ft.Container(
            content=ft.Row(
                header_row_content,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.all(Theme.Spacing.SM),
            on_hover=self._on_hover,
        )

        # Wrap header in gesture detector
        self.header_gesture = ft.GestureDetector(
            content=self.card_header,
            on_tap=self._handle_click,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        self.content = self.header_gesture
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state change."""
        if self._is_selected:
            return  # Don't change hover state when selected
        if e.data == "true":
            self.card_header.bgcolor = ft.Colors.with_opacity(
                0.08, ft.Colors.ON_SURFACE
            )
        else:
            self.card_header.bgcolor = None
        if e.control.page:
            self.card_header.update()

    def _handle_click(self, e: ft.ControlEvent) -> None:
        """Handle card click to update inspector."""
        _ = e
        if self._inspector:
            self._inspector.select_card(self)

    def set_selected(self, selected: bool) -> None:
        """Update visual state for selection."""
        self._is_selected = selected
        if selected:
            self.border = ft.border.all(2, Theme.Colors.ACCENT)
            self.bgcolor = ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE)
        else:
            self.border = ft.border.all(1, ft.Colors.OUTLINE)
            self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.update()


class FlowSection(ft.Container):
    """A section in the lifecycle flow with label and cards."""

    def __init__(
        self, title: str, cards: list[LifecycleCard], icon: str, step_number: int
    ) -> None:
        """
        Initialize flow section.

        Args:
            title: Section title
            cards: List of LifecycleCard components
            icon: Icon name for the section header
            step_number: Execution order number (1, 2, 3...)
        """
        super().__init__()
        self.title = title
        self.cards_list = cards

        # Section header with step number and icon
        section_header = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=SecondaryText(f"{step_number:02d}", size=10),
                        bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                        border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    ),
                    ft.Icon(icon, size=18, color=Theme.Colors.TEXT_SECONDARY),
                    H3Text(title),
                    ft.Container(
                        content=SecondaryText(f"({len(cards)})"),
                        padding=ft.padding.only(left=Theme.Spacing.XS),
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            ),
            padding=ft.padding.only(bottom=Theme.Spacing.SM),
        )

        # Cards row (wraps if many items)
        if cards:
            cards_row = ft.Row(
                cards,
                wrap=True,
                spacing=Theme.Spacing.MD,
                run_spacing=Theme.Spacing.MD,
                alignment=ft.MainAxisAlignment.CENTER,
            )
        else:
            cards_row = ft.Container(
                content=SecondaryText("None configured"),
                padding=ft.padding.all(Theme.Spacing.MD),
                alignment=ft.alignment.center,
            )

        self.content = ft.Column(
            [section_header, cards_row],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.SM)
