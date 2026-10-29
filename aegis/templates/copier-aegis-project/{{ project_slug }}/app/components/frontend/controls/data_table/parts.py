"""The pieces a table is assembled from: a column, a header, a row."""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls.expand_arrow import (
    EXPAND_ICON_WIDTH,
)
from app.components.frontend.theme import AegisTheme as Theme

from .cells import DataTableColumn, build_cell, header_cell, style_cell


class DataTableHeader(ft.Container):
    """Table header row with column labels."""

    def __init__(
        self,
        columns: list[DataTableColumn],
        padding: int = 10,
        show_border: bool = True,
    ) -> None:
        super().__init__()

        cells = [header_cell(col) for col in columns]

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


def set_revealed(control: ft.Control, revealed: bool) -> None:
    """Show or hide a hover-revealed control without moving the layout.

    Opacity rather than ``visible``: a hidden control collapses, so the row
    changes height as the pointer crosses the table and the whole thing reads
    as twitching. The control is disabled while hidden, because an invisible
    button that still takes clicks is worse than a visible one.
    """
    control.opacity = 1 if revealed else 0
    control.disabled = not revealed


class SelectionCheckbox(ft.Checkbox):
    """A ``DataTable`` selection toggle - the header's select-all box or
    one row's own box. Scaled down from Flet's default checkbox size so
    it doesn't dominate a table row the way the un-scaled control does.
    """

    def __init__(self, checked: bool, on_toggle: Callable[[bool], None]) -> None:
        super().__init__(
            value=checked,
            on_change=lambda e: on_toggle(bool(e.control.value)),
            scale=0.85,
        )


_SELECTION_CELL_WIDTH = 36
# A row's tint under the pointer.
HOVER_TINT = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
# What a row may hold that its hover tint must not repaint: repainting the
# row rebuilds it, so an open menu closes and a field loses its place.
_FIELDS = (ft.Dropdown, ft.TextField)


def holds_a_field(controls: list[Any]) -> bool:
    """Whether a row of ``controls`` holds one of ``_FIELDS``: its hover
    tint is left out (both tables' rows)."""
    return any(
        isinstance(c, _FIELDS)
        or (isinstance(c, ft.Control) and holds_a_field(c._get_children()))
        for c in controls
    )


class DataTableRow(ft.Container):
    """Single data row with hover effect and column-driven styling.

    A cell control marked ``reveal_on_hover = True`` is shown only while the
    pointer is over its row: row actions stay out of the way until wanted,
    without the table becoming a wall of buttons. A control can clear its own
    flag to pin itself visible - what an action in flight does, so a spinner
    does not vanish when the pointer wanders off. A row holding a field
    (``holds_a_field``) is never tinted, nor repainted but to reveal one.
    """

    def __init__(
        self,
        columns: list[DataTableColumn],
        row_data: list[Any],
        padding: int = 10,
        bgcolor: str = ft.Colors.SURFACE,
        show_border: bool = True,
        on_click: Callable[[ft.ControlEvent], None] | None = None,
        leading: ft.Control | None = None,
        leading_arrow: ft.Control | None = None,
        on_hover_change: Callable[["DataTableRow", bool], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_hover_change = on_hover_change

        cells: list[ft.Control] = []
        if leading_arrow is not None:
            cells.append(ft.Container(content=leading_arrow, width=EXPAND_ICON_WIDTH))
        if leading is not None:
            cells.append(ft.Container(content=leading, width=_SELECTION_CELL_WIDTH))
        self._hover_revealed: list[ft.Control] = []
        for i, value in enumerate(row_data):
            col = columns[i] if i < len(columns) else DataTableColumn("")
            if getattr(value, "reveal_on_hover", False):
                self._hover_revealed.append(value)
                set_revealed(value, False)
            cells.append(build_cell(col, style_cell(value, col.style)))

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
        self._tints = not holds_a_field(row_data)
        self.on_hover = self._on_hover
        if on_click is not None:
            # Whole-row affordance: ink ripple + pointer so a row reads as
            # clickable (used for drill-through to a detail view).
            self.on_click = on_click
            self.ink = True

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state change.

        The tint is cleared by the EXIT event in the normal case - but a
        virtualized row that scrolls out from under the pointer unmounts
        before that event fires, so the tint would stick in this row's
        state and ride back in on remount. ``on_hover_change`` is the
        table-level correction: the owner clears the previous holder on
        every enter, so at most one row ever wears the tint.
        """
        hovered = e.data == "true"
        if self._tints:
            e.control.bgcolor = HOVER_TINT if hovered else self._default_bgcolor
        for control in self._hover_revealed:
            # Re-read the flag each time: a control that pinned itself visible
            # while its action runs must not be hidden again on pointer-out.
            if getattr(control, "reveal_on_hover", False):
                set_revealed(control, hovered)
        if self._on_hover_change is not None:
            self._on_hover_change(self, hovered)
        if self._repaints and e.control.page:  # only once it is on a page
            e.control.update()

    @property
    def _repaints(self) -> bool:
        """Whether hovering changes how the row looks: its tint, or an
        action it reveals."""
        return self._tints or bool(self._hover_revealed)

    def clear_hover(self) -> None:
        """Reset the hover tint from outside - the stuck-state cure."""
        self.bgcolor = self._default_bgcolor
        for control in self._hover_revealed:
            if getattr(control, "reveal_on_hover", False):
                set_revealed(control, False)
        if self._repaints and self.page:
            self.update()
