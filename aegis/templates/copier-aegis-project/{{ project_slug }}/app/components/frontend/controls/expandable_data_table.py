"""
Expandable DataTable Components

Class-based composition for expandable table rows with consistent styling.
"""

from dataclasses import dataclass
from typing import Any

import flet as ft

from app.components.frontend.controls.data_table import (
    DataTableColumn,
    get_alignment,
    style_cell,
)
from app.components.frontend.controls.expand_arrow import ExpandArrow
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

EXPAND_ICON_WIDTH = 24  # Fixed width for expand arrow column


@dataclass
class ExpandableRow:
    """Row data with expandable content."""

    cells: list[Any]  # Strings auto-styled, controls passed through
    expanded_content: ft.Control
    initially_expanded: bool = False


class ExpandableTableHeader(ft.Container):
    """Table header row with space for expand arrow."""

    def __init__(
        self,
        columns: list[DataTableColumn],
        padding: int = 10,
    ) -> None:
        super().__init__()

        # Space for arrow + column headers
        cells: list[ft.Control] = [ft.Container(width=EXPAND_ICON_WIDTH)]
        cells.extend(
            ft.Container(
                content=SecondaryText(col.header, size=Theme.Typography.BODY_SMALL),
                # width is a proportional flex weight: columns split the
                # full container width in the declared ratios, so tables
                # always fill their space with no dead right-hand gap.
                expand=col.width if col.width is not None else 1,
                alignment=get_alignment(col.alignment),
            )
            for col in columns
        )

        self.content = ft.Row(cells, spacing=Theme.Spacing.MD)
        self.padding = ft.padding.symmetric(
            horizontal=Theme.Spacing.MD, vertical=padding + 2
        )
        self.border = ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE))


class ExpandableTableRow(ft.Container):
    """Expandable row with arrow, hover effect, and collapsible content."""

    def __init__(
        self,
        columns: list[DataTableColumn],
        row: ExpandableRow,
        is_expanded: bool,
        on_toggle: ft.ControlEvent,
    ) -> None:
        super().__init__()

        # Arrow using reusable control
        expand_arrow = ExpandArrow(expanded=is_expanded)

        # Build cells: arrow + data cells
        cells: list[ft.Control] = [
            ft.Container(content=expand_arrow, width=EXPAND_ICON_WIDTH)
        ]
        for i, value in enumerate(row.cells):
            col = columns[i] if i < len(columns) else DataTableColumn("")
            cells.append(
                ft.Container(
                    content=style_cell(value, col.style),
                    # width as proportional flex weight (see header cells).
                    expand=col.width if col.width is not None else 1,
                    alignment=get_alignment(col.alignment),
                )
            )

        # Row container with hover
        row_container = ft.Container(
            content=ft.Row(
                cells,
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.MD, vertical=10),
            on_hover=self._on_hover,
            # Animation disabled for debugging
            # animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        )

        # Clickable wrapper
        main_row = ft.GestureDetector(
            content=row_container,
            on_tap=on_toggle,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        # Expanded content
        expanded_container = ft.Container(
            content=row.expanded_content,
            visible=is_expanded,
            padding=ft.padding.only(
                top=Theme.Spacing.SM,
                left=Theme.Spacing.MD + EXPAND_ICON_WIDTH,
                right=Theme.Spacing.MD,
                bottom=Theme.Spacing.MD,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )

        self.content = ft.Column([main_row, expanded_container], spacing=0)
        self.border = ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE))

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state change."""
        if e.data == "true":
            e.control.bgcolor = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        else:
            e.control.bgcolor = ft.Colors.SURFACE
        if e.control.page:  # Guard: only update if control is on page
            e.control.update()


class ExpandableDataTable(ft.Container):
    """
    Composed expandable table with header and expandable rows.

    Usage:
        columns = [
            DataTableColumn("Name", style="primary"),
            DataTableColumn("Status", width=100),
        ]
        rows = [
            ExpandableRow(
                cells=["Item 1", Tag("Active")],
                expanded_content=ft.Text("Details here"),
            ),
        ]
        table = ExpandableDataTable(columns=columns, rows=rows)
    """

    def __init__(
        self,
        columns: list[DataTableColumn],
        rows: list[ExpandableRow],
        row_padding: int = 10,
        empty_message: str = "No data available",
    ) -> None:
        """
        Initialize ExpandableDataTable.

        Args:
            columns: List of column definitions with optional style
            rows: List of ExpandableRow instances
            row_padding: Vertical padding for each row (default: 10)
            empty_message: Message shown when rows is empty
        """
        super().__init__()
        self._columns = columns
        self._rows = rows
        self._row_padding = row_padding
        self._empty_message = empty_message
        self._expanded: list[bool] = [r.initially_expanded for r in rows]

        self._build()

    def _build(self) -> None:
        """Build the complete table structure."""
        if not self._rows:
            self.content = ft.Container(
                content=SecondaryText(self._empty_message),
                padding=ft.padding.all(Theme.Spacing.LG),
                alignment=ft.alignment.center,
            )
            self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
            self.border_radius = Theme.Components.CARD_RADIUS
            self.border = ft.border.all(1, ft.Colors.OUTLINE)
            return

        # Build header and rows
        header = ExpandableTableHeader(self._columns, self._row_padding)
        table_rows: list[ft.Control] = [header]

        for idx, row in enumerate(self._rows):
            table_rows.append(
                ExpandableTableRow(
                    columns=self._columns,
                    row=row,
                    is_expanded=self._expanded[idx],
                    on_toggle=lambda _e, i=idx: self._toggle_row(i),
                )
            )

        self.content = ft.Column(table_rows, spacing=0)
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)

    def _toggle_row(self, idx: int) -> None:
        """Toggle row expansion state."""
        self._expanded[idx] = not self._expanded[idx]
        self._build()
        self.update()
