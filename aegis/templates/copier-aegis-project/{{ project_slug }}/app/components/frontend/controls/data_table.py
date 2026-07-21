"""
Reusable DataTable Components

Class-based composition for table rendering with consistent styling.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import flet as ft

from app.components.frontend.controls.text import BodyText, PrimaryText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme


@dataclass
class DataTableColumn:
    """Column definition for DataTable."""

    header: str
    width: int | None = None  # Relative flex weight (None = weight 1)
    alignment: Literal["left", "center", "right"] = "left"
    style: Literal["primary", "secondary", "body"] | None = "body"


def get_alignment(alignment: str) -> ft.Alignment:
    """Convert alignment string to Flet alignment.

    Default is ``center_left``, not ``None``. A finite-width Container
    with ``alignment=None`` stretches its content to fill the cell, which
    blows up pill-shaped controls like ``MethodBadge`` (a Container with
    no explicit width). Setting an explicit alignment keeps controls at
    their natural size, anchored to the cell edge; text cells are
    unaffected because their content already left-aligns naturally.
    """
    if alignment == "right":
        return ft.alignment.center_right
    elif alignment == "center":
        return ft.alignment.center
    return ft.alignment.center_left


def style_cell(value: Any, style: str | None) -> ft.Control:
    """Apply column style to cell value.

    Args:
        value: Cell value - controls passed through, others converted to styled text
        style: Column style ("primary", "secondary", "body", or None)

    Returns:
        Styled Flet control
    """
    if isinstance(value, ft.Control):
        return value

    text = str(value)
    if style == "primary":
        return PrimaryText(text, size=Theme.Typography.BODY)
    elif style == "secondary":
        return SecondaryText(text, size=Theme.Typography.BODY)
    return BodyText(text)


class DataTableHeader(ft.Container):
    """Table header row with column labels."""

    def __init__(
        self,
        columns: list[DataTableColumn],
        padding: int = 10,
        show_border: bool = True,
    ) -> None:
        super().__init__()

        cells = [
            ft.Container(
                content=SecondaryText(col.header, size=Theme.Typography.BODY_SMALL),
                # width is a proportional flex weight: columns split the
                # full container width in the declared ratios, so tables
                # always fill their space with no dead right-hand gap.
                expand=col.width if col.width is not None else 1,
                alignment=get_alignment(col.alignment),
            )
            for col in columns
        ]

        self.content = ft.Row(cells, spacing=Theme.Spacing.MD)
        self.padding = ft.padding.symmetric(
            horizontal=Theme.Spacing.MD, vertical=padding + 2
        )
        self.bgcolor = ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)
        self.border = (
            ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE))
            if show_border
            else None
        )


class DataTableRow(ft.Container):
    """Single data row with hover effect and column-driven styling."""

    def __init__(
        self,
        columns: list[DataTableColumn],
        row_data: list[Any],
        padding: int = 10,
        bgcolor: str = ft.Colors.SURFACE,
        show_border: bool = True,
        on_click: Callable[[ft.ControlEvent], None] | None = None,
        tooltip: str | None = None,
    ) -> None:
        super().__init__()

        cells = []
        for i, value in enumerate(row_data):
            col = columns[i] if i < len(columns) else DataTableColumn("")
            cells.append(
                ft.Container(
                    content=style_cell(value, col.style),
                    # width as proportional flex weight (see header cells).
                    expand=col.width if col.width is not None else 1,
                    alignment=get_alignment(col.alignment),
                )
            )

        self._default_bgcolor = bgcolor

        self.content = ft.Row(cells, spacing=Theme.Spacing.MD)
        self.bgcolor = bgcolor
        self.padding = ft.padding.symmetric(
            horizontal=Theme.Spacing.MD, vertical=padding
        )
        self.border = (
            ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE))
            if show_border
            else None
        )
        if tooltip:
            self.tooltip = tooltip
        self.on_hover = self._on_hover
        if on_click is not None:
            # Whole-row affordance: ink ripple + pointer so a row reads as
            # clickable (used for drill-through to a detail view).
            self.on_click = on_click
            self.ink = True
        # Animation disabled for debugging
        # self.animate = ft.Animation(150, ft.AnimationCurve.EASE_OUT)

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state change."""
        if e.data == "true":
            e.control.bgcolor = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        else:
            e.control.bgcolor = self._default_bgcolor
        if e.control.page:  # Guard: only update if control is on page
            e.control.update()


class DataTable(ft.Container):
    """
    Composed table with header and data rows.

    Usage:
        columns = [
            DataTableColumn("Name", width=200, style="primary"),
            DataTableColumn("Value", width=100, alignment="right", style="secondary"),
            DataTableColumn("Status"),  # expands, passes through controls
        ]
        rows = [
            ["Row 1", "100", Tag("Active", color=GREEN)],
            ["Row 2", "200", Tag("Inactive", color=GREY)],
        ]
        table = DataTable(columns=columns, rows=rows)
    """

    def __init__(
        self,
        columns: list[DataTableColumn],
        rows: list[list[Any]],
        row_padding: int = 10,
        scroll_height: int | None = None,
        empty_message: str = "No data available",
        show_header_border: bool = True,
        show_row_borders: bool = True,
        row_bgcolors: list[str | None] | None = None,
        on_row_click: Callable[[int], None] | None = None,
        row_tooltips: list[str] | None = None,
        expand: bool = False,
    ) -> None:
        """
        Initialize DataTable.

        Args:
            columns: List of column definitions with optional style
            rows: List of rows (strings auto-styled, controls passed through)
            row_padding: Vertical padding for each row (default: 10)
            scroll_height: If set, wraps rows in ListView with this height
            empty_message: Message shown when rows is empty
            show_header_border: Show bottom border on header (default: True)
            show_row_borders: Show bottom border on each row (default: True)
            row_bgcolors: Optional list of background colors per row
            expand: If True, table expands to fill available space with scroll
        """
        super().__init__()

        # Build header
        header = DataTableHeader(columns, row_padding, show_header_border)

        # Build data rows or empty state
        if not rows:
            from app.components.frontend.dashboard.modals.modal_sections import (
                EmptyStatePlaceholder,
            )

            data_content: ft.Control = EmptyStatePlaceholder(empty_message)
        else:
            # Build rows with optional custom bgcolors
            data_rows: list[ft.Control] = []
            for idx, row_data in enumerate(rows):
                bgcolor = ft.Colors.SURFACE
                if row_bgcolors and idx < len(row_bgcolors) and row_bgcolors[idx]:
                    bgcolor = row_bgcolors[idx]

                data_rows.append(
                    DataTableRow(
                        columns=columns,
                        row_data=row_data,
                        padding=row_padding,
                        bgcolor=bgcolor,
                        show_border=show_row_borders,
                        on_click=(
                            (lambda _e, i=idx: on_row_click(i))
                            if on_row_click is not None
                            else None
                        ),
                        tooltip=(
                            row_tooltips[idx]
                            if row_tooltips and idx < len(row_tooltips)
                            else None
                        ),
                    )
                )

            if scroll_height:
                # Fixed height scrolling
                data_content = ft.ListView(
                    controls=data_rows,
                    spacing=0,
                    height=scroll_height,
                )
            elif expand:
                # Expand to fill available space with scrolling
                data_content = ft.ListView(
                    controls=data_rows,
                    spacing=0,
                    expand=True,
                )
            else:
                # No scrolling, auto-height
                data_content = ft.Column(data_rows, spacing=0)

        # Compose table
        self.content = ft.Column([header, data_content], spacing=0, expand=expand)
        self.bgcolor = ft.Colors.SURFACE
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        if expand:
            self.expand = True
