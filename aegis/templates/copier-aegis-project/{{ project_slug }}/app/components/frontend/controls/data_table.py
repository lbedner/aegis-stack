"""
Reusable DataTable Components

Class-based composition for table rendering with consistent styling.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import flet as ft

from app.components.frontend.controls.expand_arrow import (
    EXPAND_ICON_WIDTH,
    ExpandArrow,
)
from app.components.frontend.controls.text import BodyText, PrimaryText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme


@dataclass
class DataTableColumn:
    """Column definition for DataTable."""

    header: str
    width: int | None = None  # Fixed pixel width (None = expand to fill)
    alignment: Literal["left", "center", "right"] = "left"
    style: Literal["primary", "secondary", "body"] | None = "body"
    # Header click sorts the table by this column. Columns whose cells
    # carry no extractable text (action buttons) ignore clicks anyway;
    # set False to opt a column out explicitly.
    sortable: bool = True
    # Column-picker participation (tables built with ``column_picker=True``):
    # ``hideable=False`` keeps a column out of the picker menu entirely
    # (identity columns, action gutters); ``visible=False`` ships it
    # hidden-by-default, one menu click away.
    hideable: bool = True
    visible: bool = True


# Distinguishes "not passed" from an explicit None in set_rows.
_UNSET: Any = object()

# Cell texts that mean "no value" - they sort after everything real.
_BLANK_CELL_TEXTS = frozenset({"", "—", "-", "–"})


def _cell_text(cell: Any) -> str | None:
    """Best-effort text of a cell for sorting.

    ``.data`` wins whenever it is set: it is the builder's explicit sort
    key, and the only reason to stamp it is that the cell should NOT sort
    by what it displays. Two cases need that. A cell with real interactive
    content (buttons, a Row of controls) has no single ``.value`` to read,
    so ``.data`` is the only text there is. And a cell whose display text
    sorts wrong - a humanized date reading "Aug 1, 2026", which collates
    before "Sep 21, 2025" alphabetically - stamps the ISO string so it
    sorts chronologically. If ``.data`` did not outrank ``.value`` that
    second case would silently sort by the pretty text instead.

    Otherwise: plain strings, ``ft.Text`` subclasses (``.value``), and
    single-text wrappers like ``Tag`` (``.content.value``)."""
    if isinstance(cell, str):
        return cell
    data = getattr(cell, "data", None)
    if isinstance(data, str) and data:
        return data
    value = getattr(cell, "value", None)
    if isinstance(value, str):
        return value
    inner = getattr(getattr(cell, "content", None), "value", None)
    if isinstance(inner, str):
        return inner
    return None


def _cell_sort_key(cell: Any) -> tuple[int, float, str] | None:
    """Type-ranked sort key: numbers (incl. ``$1,200.00``, ``4.6G``,
    ``12%``) first, then text case-insensitively, then blanks. ``None``
    means the cell has nothing to sort by."""
    text = _cell_text(cell)
    if text is None:
        return None
    stripped = text.strip()
    if stripped in _BLANK_CELL_TEXTS:
        return (2, 0.0, "")
    cleaned = stripped.replace("$", "").replace(",", "").replace("%", "")
    try:
        return (0, float(cleaned), "")
    except ValueError:
        pass
    # One trailing unit letter ("4.6G", "19.4G") still reads as a number.
    if len(cleaned) > 1:
        try:
            return (0, float(cleaned[:-1]), "")
        except ValueError:
            pass
    return (1, 0.0, stripped.casefold())


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


# Public, because a caller that passes an already-built control skips
# ``style_cell`` entirely and has to apply these itself to match. Without
# them the control WRAPS while every plain-value cell beside it ellipses,
# which shows up as one table row growing to two lines.
# The column-picker button occupies a whole trailing gutter that is not
# a column. A caller sizing a container to fit the table has to add it,
# so it is public rather than buried in the class.
PICKER_GUTTER_WIDTH = 28


CELL_ELLIPSIS_KWARGS = {
    "max_lines": 1,
    "overflow": ft.TextOverflow.ELLIPSIS,
    "no_wrap": True,
}


def style_cell(value: Any, style: str | None) -> ft.Control:
    """Apply column style to cell value.

    Args:
        value: Cell value - controls passed through, others converted to styled text
        style: Column style ("primary", "secondary", "body", or None)

    Returns:
        Styled Flet control

    A value here truncates with an ellipsis rather than wrapping: the row
    it lands in has one fixed height, so a second line just gets clipped
    by that height instead of showing anything. A value passed as an
    already-built control (the ``isinstance`` branch) is the caller's own
    responsibility - build it single-line too if it can run long.
    """
    if isinstance(value, ft.Control):
        return value

    text = str(value)
    if style == "primary":
        return PrimaryText(text, size=Theme.Typography.BODY, **CELL_ELLIPSIS_KWARGS)
    elif style == "secondary":
        return SecondaryText(text, size=Theme.Typography.BODY, **CELL_ELLIPSIS_KWARGS)
    return BodyText(text, **CELL_ELLIPSIS_KWARGS)


# Native (Flutter) tooltips on table CELLS follow the pointer and pop up
# over neighbouring rows, which turns scrolling a long register into a
# game of whack-a-tooltip (user-reported). Cells are stripped of them by
# default; flip this to restore every cell tooltip product-wide. Chrome
# OUTSIDE the rows (the column picker, toolbar buttons) keeps its
# tooltips - those sit still under the pointer.
CELL_TOOLTIPS_ENABLED = False


def _clear_tooltips(control: ft.Control, depth: int = 0) -> None:
    """Blank ``tooltip`` on a cell control and its children.

    Bounded recursion: cell content is shallow (a Row of texts and
    buttons at most). ``default_tooltip`` is PulseButton's stash for
    re-applying the tooltip on enable/disable toggles - blank it too or
    the tooltip resurrects the first time a row button flips state.
    """
    if depth > 4:
        return
    if getattr(control, "tooltip", None) is not None:
        control.tooltip = None
    if getattr(control, "default_tooltip", None) is not None:
        control.default_tooltip = None
    child = getattr(control, "content", None)
    if isinstance(child, ft.Control):
        _clear_tooltips(child, depth + 1)
    for item in getattr(control, "controls", None) or []:
        if isinstance(item, ft.Control):
            _clear_tooltips(item, depth + 1)


def build_cell(column: DataTableColumn, content: ft.Control) -> ft.Container:
    """Wrap cell content in its column's sizing and alignment.

    The single place column width is turned into layout, shared by the plain
    and expandable tables so the two can't drift: ``width=N`` is a fixed pixel
    width, and a width-less column expands to absorb whatever is left, so a
    table fills its container with no dead right-hand gap.

    Passing the width as a flex weight instead collapses every width-less
    column to a sliver (the fixed widths are pixel-scale, so they win the
    ratio by two orders of magnitude) and its text wraps one character per
    line. Both tables have shipped that bug; this helper exists so a fix
    lands in one place.
    """
    if not CELL_TOOLTIPS_ENABLED:
        _clear_tooltips(content)
    return ft.Container(
        content=content,
        width=column.width,
        expand=column.width is None,
        alignment=get_alignment(column.alignment),
    )


def header_cell(column: DataTableColumn) -> ft.Container:
    """The column's header label, sized like its data cells."""
    return build_cell(
        column, SecondaryText(column.header, size=Theme.Typography.BODY_SMALL)
    )


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


_SELECTION_CELL_WIDTH = 36


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


class DataTableRow(ft.Container):
    """Single data row with hover effect and column-driven styling.

    A cell control marked ``reveal_on_hover = True`` is shown only while the
    pointer is over its row: row actions stay out of the way until wanted,
    without the table becoming a wall of buttons. A control can clear its own
    flag to pin itself visible - what an action in flight does, so a spinner
    does not vanish when the pointer wanders off.
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
        self.on_hover = self._on_hover
        if on_click is not None:
            # Whole-row affordance: ink ripple + pointer so a row reads as
            # clickable (used for drill-through to a detail view).
            self.on_click = on_click
            self.ink = True
        # Animation disabled for debugging
        # self.animate = ft.Animation(150, ft.AnimationCurve.EASE_OUT)

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
        if hovered:
            e.control.bgcolor = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        else:
            e.control.bgcolor = self._default_bgcolor
        for control in self._hover_revealed:
            # Re-read the flag each time: a control that pinned itself visible
            # while its action runs must not be hidden again on pointer-out.
            if getattr(control, "reveal_on_hover", False):
                set_revealed(control, hovered)
        if self._on_hover_change is not None:
            self._on_hover_change(self, hovered)
        if e.control.page:  # Guard: only update if control is on page
            e.control.update()

    def clear_hover(self) -> None:
        """Reset the hover tint from outside - the stuck-state cure."""
        self.bgcolor = self._default_bgcolor
        for control in self._hover_revealed:
            if getattr(control, "reveal_on_hover", False):
                set_revealed(control, False)
        if self.page:
            self.update()


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
        item_extent: int | None = None,
        empty_message: str = "No data available",
        show_header_border: bool = True,
        show_row_borders: bool = True,
        row_bgcolors: list[str | None] | None = None,
        on_row_click: Callable[[int], None] | None = None,
        expand: bool = False,
        pinned_last_rows: int = 0,
        initial_sort: int | None = None,
        initial_sort_desc: bool = False,
        column_picker: bool = False,
        selectable: bool = False,
        row_selectable: Callable[[int], bool] | None = None,
        selected_indices: set[int] | None = None,
        on_selection_change: Callable[[set[int]], None] | None = None,
        expandable_content: Callable[[int], ft.Control] | None = None,
    ) -> None:
        """
        Initialize DataTable.

        Args:
            columns: List of column definitions with optional style
            rows: List of rows (strings auto-styled, controls passed through)
            row_padding: Vertical padding for each row (default: 10)
            scroll_height: If set, wraps rows in ListView with this height
            item_extent: Fixed row height, when every row renders at the
                same height (uniform cells, no wrapping). ListView already
                only builds on-screen rows either way, but without a known
                item extent Flutter still has to lay out each row to learn
                its size before it can place the next one - a table whose
                rows carry a live control per cell (e.g. a dropdown) rather
                than plain text is heavy enough per-row that this shows up
                as sluggish scrolling despite virtualization already being
                on. Passing the row's real height lets it compute scroll
                offsets analytically instead, skipping that per-row pass.
            empty_message: Message shown when rows is empty
            show_header_border: Show bottom border on header (default: True)
            show_row_borders: Show bottom border on each row (default: True)
            row_bgcolors: Optional list of background colors per row
            expand: If True, table expands to fill available space with scroll
            pinned_last_rows: Trailing rows exempt from sorting (totals rows)
            initial_sort: Column index to sort by on first render (header
                shows the arrow; clicking still re-sorts as usual)
            initial_sort_desc: Sort the initial column descending
            column_picker: Render a columns menu at the header's right
                edge for showing/hiding ``hideable`` columns. All indices
                (sorting, row-click, tooltips) stay original-column-based.
            selectable: Adds a checkbox column (row + header select-all).
                Selection is owned by the table itself between renders -
                toggling one row updates in place (no full rebuild, so it
                stays cheap on a large table); "select all" is the one
                selection action that does re-render, since every visible
                checkbox has to flip. ``selected_indices`` seeds the
                initial selection (original row indices, same addressing
                as ``on_row_click``); pass the caller's own current
                selection back in whenever the table itself gets rebuilt
                for an unrelated reason (new data, a resort), so a
                selection survives that rebuild instead of resetting.
            on_selection_change: Called with the full current selection
                (original row indices) after every change.
            expandable_content: When given, a row click toggles an inline
                expansion panel below it (built lazily, on first expand,
                from this callback) instead of firing ``on_row_click`` -
                the two are mutually exclusive, no current table needs
                both. Any number of rows can be open at once, same as
                ``ExpandableDataTable``.

        Every column with extractable cell text is sortable by clicking its
        header (ascending, then descending); ``on_row_click`` and per-row
        tooltips/colors always follow their ORIGINAL row indices.
        """
        super().__init__()
        self._columns = columns
        self._rows = rows
        self._row_padding = row_padding
        self._scroll_height = scroll_height
        self._item_extent = item_extent
        self._empty_message = empty_message
        self._show_header_border = show_header_border
        self._show_row_borders = show_row_borders
        self._row_bgcolors = row_bgcolors
        self._on_row_click = on_row_click
        self._expand_table = expand
        self._pinned_last_rows = max(0, pinned_last_rows)
        self._column_picker = column_picker
        self._col_visible = [c.visible for c in columns]
        valid_initial = (
            initial_sort is not None
            and 0 <= initial_sort < len(columns)
            and columns[initial_sort].sortable
        )
        self._sort_column: int | None = initial_sort if valid_initial else None
        self._sort_desc = initial_sort_desc if valid_initial else False
        self._selectable = selectable
        # Per-row opt-out. A merged table (the register's transactions +
        # trades) has rows the bulk actions can never apply to; giving
        # those a checkbox that silently counts for nothing reads as the
        # whole feature being broken - especially when they sort to the
        # top. No checkbox = no lie.
        self._row_selectable = row_selectable
        self._on_selection_change = on_selection_change
        self._selected: set[int] = set(selected_indices) if selected_indices else set()
        self._select_all_checkbox: SelectionCheckbox | None = None
        # Indexed by original row index (not display position), so
        # _toggle_all can flip every checkbox's own .value in place
        # without rebuilding the row it lives in. Repopulated by every
        # _render(); a checkbox that's currently sorted out of view is
        # still in here and still gets updated - it's just not painted.
        self._row_checkboxes: list[SelectionCheckbox | None] = []
        self._expandable_content = expandable_content
        # Original row index -> already-built expansion content. Persists
        # across re-renders triggered by something unrelated (a resort, a
        # column-picker toggle) so an already-open row's detail panel isn't
        # rebuilt for free; scoped to this DataTable instance, so a fresh
        # data load (a brand new DataTable(...)) starts with an empty one.
        self._expand_cache: dict[int, ft.Control] = {}
        self._expanded: set[int] = set()
        # Repopulated by every _render(), same lifetime/reset rule as
        # _row_checkboxes above. Lets _toggle_expand mutate ONE row (flip
        # its arrow, splice its expansion panel in/out of the already-
        # mounted list) instead of rebuilding and replacing every row on
        # the table via a fresh _render() + self.update() - a full-tree
        # content swap mid-click was the toggle needing two clicks to
        # take effect (confirmed live: reverted from an earlier version
        # that called _render() here, same as _on_sort/_toggle_column do
        # for their own, much less frequent, state changes).
        self._row_controls: dict[int, DataTableRow] = {}
        self._row_arrows: dict[int, ExpandArrow] = {}
        self._expand_widgets: dict[int, ft.Container] = {}
        self._data_content: ft.Control | None = None
        # The invariant that makes hover self-healing: at most one row
        # wears the tint, enforced on every pointer-enter rather than
        # trusting exit events a virtualized unmount can swallow.
        self._hovered_row: DataTableRow | None = None
        # The mounted skeleton, built ONCE. Scroll position lives in the
        # Flutter element behind the ListView, and replacing ANY ancestor
        # remounts the subtree and forgets it - so ``_render()`` only ever
        # swaps these hosts' contents, and the ListView itself is created
        # once and mutated thereafter. ``_toggle_expand`` proved the
        # mechanism; this makes it the rule.
        self._header_host = ft.Container()
        self._data_host = ft.Container(expand=expand)
        self._listview: ft.ListView | None = None

        self.bgcolor = ft.Colors.SURFACE
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        if expand:
            self.expand = True
        self.content = ft.Column(
            [self._header_host, self._data_host],
            spacing=0,
            expand=self._expand_table,
        )
        self._render()

    def set_rows(
        self,
        rows: list[list[Any]],
        *,
        row_bgcolors: Any = _UNSET,
        expandable_content: Any = _UNSET,
        on_selection_change: Any = _UNSET,
        on_row_click: Any = _UNSET,
        selected_indices: set[int] | None = None,
    ) -> None:
        """Feed the table new data IN PLACE of a rebuild.

        The whole point is what it does not do: the mounted ListView (and
        everything above it) survives, so the reader's scroll position
        survives the update. Constructing a fresh DataTable per data load
        - the register's old edit loop - snapped every categorize back to
        the top of the table.

        The sort choice persists across new data (a sorted table must not
        silently unsort because a row was edited). Selection and expanded
        rows reset by default - the old row indices point at the old data
        - but ``selected_indices`` can seed a carried selection, and the
        callback keywords let a caller whose closures capture the fetched
        rows hand over fresh ones. Omitted keywords keep what the table
        already has.
        """
        self._rows = rows
        if row_bgcolors is not _UNSET:
            self._row_bgcolors = row_bgcolors
        if expandable_content is not _UNSET:
            self._expandable_content = expandable_content
        if on_selection_change is not _UNSET:
            self._on_selection_change = on_selection_change
        if on_row_click is not _UNSET:
            self._on_row_click = on_row_click
        self._selected = set(selected_indices) if selected_indices else set()
        self._expanded.clear()
        self._expand_cache.clear()
        self._expand_widgets = {}
        self._render()
        if self.page is not None:
            self.update()

    # -- sorting -----------------------------------------------------------

    def _sortable_span(self) -> int:
        """Rows that participate in sorting (pinned tail excluded)."""
        return len(self._rows) - self._pinned_last_rows

    def _column_keys(self, index: int) -> list[tuple[int, float, str] | None]:
        return [
            _cell_sort_key(row[index]) if index < len(row) else None
            for row in self._rows[: self._sortable_span()]
        ]

    def _on_sort(self, index: int) -> None:
        """Header click: sort by ``index`` (asc, then desc on re-click)."""
        if index >= len(self._columns) or not self._columns[index].sortable:
            return
        if all(key is None for key in self._column_keys(index)):
            return  # nothing extractable to sort by (an actions column)
        if self._sort_column == index:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column = index
            self._sort_desc = False
        self._render()
        if self.page is not None:
            self.update()

    def _display_order(self) -> list[int]:
        """Original row indices in display order (pinned tail last)."""
        span = self._sortable_span()
        order = list(range(span))
        if self._sort_column is not None:
            keys = self._column_keys(self._sort_column)

            # Blank and missing cells lose in BOTH directions - reversing a
            # column should flip the values, not hoist the rows that have
            # nothing to say into first place.
            def _is_blank(key: tuple[int, float, str] | None) -> bool:
                return key is None or key[0] >= 2

            keyed = [i for i in order if not _is_blank(keys[i])]
            blanks = [i for i in order if _is_blank(keys[i])]
            keyed.sort(key=lambda i: keys[i], reverse=self._sort_desc)
            order = keyed + blanks
        return order + list(range(span, len(self._rows)))

    # -- selection -----------------------------------------------------------

    def _selectable_set(self) -> set[int]:
        """Row indices selection applies to (see ``row_selectable``)."""
        if self._row_selectable is None:
            return set(range(len(self._rows)))
        return {i for i in range(len(self._rows)) if self._row_selectable(i)}

    def _selection_header_cell(self) -> ft.Container:
        # Fills against the SELECTABLE count: with two of three rows
        # eligible, checking both must read "all selected", not sit at
        # two-thirds forever.
        total = len(self._selectable_set())
        checkbox = SelectionCheckbox(
            checked=bool(total) and len(self._selected) >= total,
            on_toggle=self._toggle_all,
        )
        self._select_all_checkbox = checkbox
        return ft.Container(content=checkbox, width=_SELECTION_CELL_WIDTH)

    def _selection_row_cell(self, idx: int) -> ft.Control | None:
        """The row's checkbox, or ``None`` for a row selection skips -
        the caller renders an empty spacer so columns stay aligned."""
        if self._row_selectable is not None and not self._row_selectable(idx):
            return None
        return SelectionCheckbox(
            checked=idx in self._selected,
            on_toggle=lambda checked, i=idx: self._toggle_row(i, checked),
        )

    def _emit_selection(self) -> None:
        if self._on_selection_change is not None:
            self._on_selection_change(set(self._selected))

    def _toggle_row(self, idx: int, checked: bool) -> None:
        """One row's checkbox - updates in place, no rebuild. Only the
        select-all box's own checked state needs a targeted refresh."""
        if checked:
            self._selected.add(idx)
        else:
            self._selected.discard(idx)
        if self._select_all_checkbox is not None:
            total = len(self._selectable_set())
            self._select_all_checkbox.value = (
                bool(total) and len(self._selected) >= total
            )
            if self._select_all_checkbox.page:
                self._select_all_checkbox.update()
        self._emit_selection()

    def _toggle_all(self, checked: bool) -> None:
        """Every checkbox flips - mutated on the SAME control instances a
        normal row toggle uses, not a rebuild. A rebuild was the first cut
        here and was the whole reason "select all" felt slow on 900+ rows:
        it reconstructs every row's full control tree (five cells each,
        not just the checkbox) and ships all of it to the client as brand
        new controls, which have no prior state to diff against. Setting
        ``.value`` on the existing checkboxes only touches what actually
        changed, so one ``update()`` sends just that.
        """
        self._selected = self._selectable_set() if checked else set()
        for checkbox in self._row_checkboxes:
            if checkbox is not None:
                checkbox.value = checked
        self._emit_selection()
        if self.page:
            self.update()

    # -- inline expand -------------------------------------------------------

    def _build_expand_widget(self, idx: int) -> ft.Container:
        if idx not in self._expand_cache:
            assert self._expandable_content is not None
            self._expand_cache[idx] = self._expandable_content(idx)
        return ft.Container(
            content=self._expand_cache[idx],
            padding=ft.padding.only(
                top=Theme.Spacing.SM,
                left=Theme.Spacing.MD + EXPAND_ICON_WIDTH,
                right=Theme.Spacing.MD,
                bottom=Theme.Spacing.MD,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )

    def _toggle_expand(self, idx: int) -> None:
        """Mutates the already-mounted row + its ListView/Column in
        place - no ``_render()``, no full-tree ``self.update()``. See the
        ``_row_controls`` field comment for why: a full content swap
        DURING the click that triggered it was the toggle needing two
        clicks to visibly take effect."""
        row_control = self._row_controls.get(idx)
        arrow = self._row_arrows.get(idx)
        data_content = self._data_content
        controls = getattr(data_content, "controls", None)
        if (
            row_control is None
            or arrow is None
            or data_content is None
            or controls is None
        ):
            # Not on the currently-rendered controls (shouldn't normally
            # happen for a click that just fired from one of them) - fall
            # back to a full rebuild rather than silently no-op.
            if idx in self._expanded:
                self._expanded.discard(idx)
            else:
                self._expanded.add(idx)
            self._render()
            if self.page is not None:
                self.update()
            return
        try:
            pos = controls.index(row_control)
        except ValueError:
            return

        if idx in self._expanded:
            self._expanded.discard(idx)
            arrow.set_expanded(False)
            widget = self._expand_widgets.pop(idx, None)
            if (
                widget is not None
                and pos + 1 < len(controls)
                and controls[pos + 1] is widget
            ):
                del controls[pos + 1]
        else:
            self._expanded.add(idx)
            arrow.set_expanded(True)
            widget = self._build_expand_widget(idx)
            self._expand_widgets[idx] = widget
            controls.insert(pos + 1, widget)

        # NO item_extent flip here, ever. The old empty<->non-empty flip
        # swapped Flutter's sliver type and re-anchored the viewport ~ten
        # rows off at depth; correcting with scroll_to was worse still -
        # ensure-visible aligns every ANCESTOR scrollable, so the whole
        # tab jerked sideways as if being re-selected (confirmed live,
        # both). Expandable tables never put the extent on the sliver at
        # all now - each ROW carries the fixed height instead, so there
        # is no mode to switch. See _render for where the height
        # actually lives.

        if self.page is not None:
            arrow.update()
            data_content.update()

    def _note_row_hover(self, row: DataTableRow, hovered: bool) -> None:
        """Keep at most one row tinted (see _hovered_row)."""
        if hovered:
            previous = self._hovered_row
            if previous is not None and previous is not row:
                previous.clear_hover()
            self._hovered_row = row
        elif self._hovered_row is row:
            self._hovered_row = None

    def deselect_all(self) -> None:
        """Clear the current selection in place - the public half of
        ``_toggle_all(False)``, for a caller that already knows the
        selection should reset after acting on it (e.g. a bulk action)
        without forcing a full table rebuild to get there."""
        self._toggle_all(False)

    # -- rendering ---------------------------------------------------------

    def _column_has_keys(self, index: int) -> bool:
        return any(key is not None for key in self._column_keys(index))

    def _header_cell(self, index: int, column: DataTableColumn) -> ft.Container:
        text = SecondaryText(column.header, size=Theme.Typography.BODY_SMALL)
        sortable = column.sortable and bool(self._rows) and self._column_has_keys(index)
        if not sortable:
            return build_cell(column, text)

        is_active = self._sort_column == index
        # Active column: a solid directional arrow. Inactive sortable
        # columns: a faint stacked-chevron glyph, so sortability is visible
        # before the first click instead of being a secret.
        icon = ft.Icon(
            (
                (
                    ft.Icons.ARROW_DROP_DOWN
                    if self._sort_desc
                    else ft.Icons.ARROW_DROP_UP
                )
                if is_active
                else ft.Icons.UNFOLD_MORE
            ),
            size=16 if is_active else 14,
            color=(
                ft.Colors.ON_SURFACE
                if is_active
                else ft.Colors.with_opacity(0.35, ft.Colors.ON_SURFACE_VARIANT)
            ),
        )
        if is_active:
            text.color = ft.Colors.ON_SURFACE

        def _hover(event: ft.ControlEvent) -> None:
            hovered = event.data == "true"
            text.color = (
                ft.Colors.ON_SURFACE
                if hovered or is_active
                else Theme.Colors.TEXT_SECONDARY
            )
            icon.color = (
                ft.Colors.ON_SURFACE
                if is_active
                else (
                    ft.Colors.ON_SURFACE_VARIANT
                    if hovered
                    else ft.Colors.with_opacity(0.35, ft.Colors.ON_SURFACE_VARIANT)
                )
            )
            if event.control.page is not None:
                event.control.update()

        # The interactive region hugs the label + glyph, NOT the full cell:
        # an expanding column's cell can span half the table, and a hover
        # highlight that wide reads as a mystery bar (and the bare Text
        # underneath shows a text cursor). A tight click target reads as
        # the button it is.
        interactive = ft.Container(
            content=ft.Row([text, icon], spacing=0, tight=True),
            on_click=lambda _e, i=index: self._on_sort(i),
            on_hover=_hover,
            ink=True,
            border_radius=4,
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
        )
        return build_cell(column, interactive)

    # Width of the column-picker gutter (header icon + per-row spacer,
    # so the flexible columns line up between header and body).
    _PICKER_WIDTH = PICKER_GUTTER_WIDTH

    def _visible_indices(self) -> list[int]:
        return [i for i, shown in enumerate(self._col_visible) if shown]

    def _toggle_column(self, index: int) -> None:
        # The last visible column can't be hidden - a table of nothing
        # but the picker gutter is not a table.
        if self._col_visible[index] and sum(self._col_visible) <= 1:
            return
        self._col_visible[index] = not self._col_visible[index]
        # Sorting by a column the viewer can no longer see is a mystery
        # ordering; drop back to the natural order instead.
        if not self._col_visible[index] and self._sort_column == index:
            self._sort_column = None
            self._sort_desc = False
        self._render()
        if self.page is not None:
            self.update()

    def _picker_cell(self) -> ft.Container:
        items = [
            ft.PopupMenuItem(
                text=col.header,
                checked=self._col_visible[i],
                on_click=lambda _e, i=i: self._toggle_column(i),
            )
            for i, col in enumerate(self._columns)
            if col.hideable and col.header
        ]
        return ft.Container(
            content=ft.PopupMenuButton(
                content=ft.Icon(
                    ft.Icons.VIEW_COLUMN_OUTLINED,
                    size=16,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                items=items,
                tooltip="Show or hide columns",
            ),
            width=self._PICKER_WIDTH,
            alignment=ft.alignment.center_right,
        )

    def _build_header(self) -> ft.Container:
        cells: list[ft.Control] = [
            self._header_cell(i, self._columns[i]) for i in self._visible_indices()
        ]
        if self._expandable_content is not None:
            cells = [ft.Container(width=EXPAND_ICON_WIDTH), *cells]
        if self._selectable:
            cells = [self._selection_header_cell(), *cells]
        if self._column_picker:
            cells.append(self._picker_cell())
        return ft.Container(
            content=ft.Row(
                cells,
                spacing=Theme.Spacing.MD,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.MD, vertical=self._row_padding + 2
            ),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            border=(
                ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE))
                if self._show_header_border
                else None
            ),
        )

    def _render(self) -> None:
        header = self._build_header()
        # Every row control is about to be rebuilt; a held hover ref
        # would point at a control no longer shown.
        self._hovered_row = None

        if not self._rows:
            from app.components.frontend.dashboard.modals.modal_sections import (
                EmptyStatePlaceholder,
            )

            self._row_checkboxes = []
            self._row_controls = {}
            self._row_arrows = {}
            self._expand_widgets = {}
            data_content: ft.Control = EmptyStatePlaceholder(self._empty_message)
        else:
            visible = self._visible_indices()
            row_columns = [self._columns[i] for i in visible]
            if self._column_picker:
                # Match the header's picker gutter so flex columns align.
                row_columns = [
                    *row_columns,
                    DataTableColumn("", width=self._PICKER_WIDTH),
                ]
            data_rows: list[ft.Control] = []
            row_checkboxes: list[SelectionCheckbox | None] = [None] * len(self._rows)
            self._row_controls = {}
            self._row_arrows = {}
            self._expand_widgets = {}
            for idx in self._display_order():
                full_row = self._rows[idx]
                row_data = [full_row[i] if i < len(full_row) else "" for i in visible]
                if self._column_picker:
                    row_data.append("")
                bgcolor = ft.Colors.SURFACE
                if (
                    self._row_bgcolors
                    and idx < len(self._row_bgcolors)
                    and self._row_bgcolors[idx]
                ):
                    bgcolor = self._row_bgcolors[idx]
                on_row_click = self._on_row_click
                checkbox = self._selection_row_cell(idx) if self._selectable else None
                # Spacer, not nothing: an unselectable row in a selectable
                # table still owns the checkbox gutter, or its cells shift
                # left and every column header stops lining up.
                leading_cell = checkbox
                if self._selectable and checkbox is None:
                    leading_cell = ft.Container(width=0)
                # Only real checkboxes join the toggle-all sweep.
                row_checkboxes[idx] = (
                    checkbox if isinstance(checkbox, SelectionCheckbox) else None
                )
                expandable = self._expandable_content is not None
                arrow = (
                    ExpandArrow(expanded=idx in self._expanded) if expandable else None
                )
                row_control = DataTableRow(
                    columns=row_columns,
                    row_data=row_data,
                    padding=self._row_padding,
                    bgcolor=bgcolor,
                    show_border=self._show_row_borders,
                    leading=leading_cell,
                    leading_arrow=arrow,
                    on_hover_change=self._note_row_hover,
                    on_click=(
                        (lambda _e, i=idx: self._toggle_expand(i))
                        if expandable
                        else (
                            (lambda _e, i=idx: on_row_click(i))
                            if on_row_click is not None
                            else None
                        )
                    ),
                )
                row_control.key = f"dtr-{idx}"
                if self._expandable_content is not None and self._item_extent:
                    # The fixed height lives on the ROW here, not the
                    # sliver - see the item_extent comment below.
                    row_control.height = self._item_extent
                data_rows.append(row_control)
                if expandable:
                    self._row_controls[idx] = row_control
                    assert arrow is not None
                    self._row_arrows[idx] = arrow
                if expandable and idx in self._expanded:
                    if idx not in self._expand_cache:
                        assert self._expandable_content is not None
                        self._expand_cache[idx] = self._expandable_content(idx)
                    expand_widget = ft.Container(
                        content=self._expand_cache[idx],
                        padding=ft.padding.only(
                            top=Theme.Spacing.SM,
                            left=Theme.Spacing.MD + EXPAND_ICON_WIDTH,
                            right=Theme.Spacing.MD,
                            bottom=Theme.Spacing.MD,
                        ),
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    )
                    self._expand_widgets[idx] = expand_widget
                    data_rows.append(expand_widget)
            self._row_checkboxes = row_checkboxes

            # A collapsed table's rows are all the SAME height, so
            # item_extent (when the caller passed one) keeps ListView's
            # O(1) analytic scroll math. An expanded row inserts a second,
            # taller ListView item right after it - item_extent applies
            # uniformly to every item, so the moment anything is expanded
            # it would clip that item to the fixed row height instead of
            # its real content height. Dropping it only while
            # self._expanded is non-empty costs the per-row layout pass
            # item_extent exists to skip, but only for as long as a row
            # is actually open - a transient, human-paced state, not the
            # bulk-scroll case item_extent optimizes for.
            # The sliver-level extent is reserved for tables that can
            # NEVER hold a taller-than-a-row item: with expandable rows
            # the panel would be clipped, and toggling the extent off
            # while a panel is open swaps the sliver type and re-anchors
            # the scroll (the ten-rows-up jump). Expandable tables put
            # the fixed height on each row instead - same cheap layout,
            # one sliver mode for the ListView's whole life.
            item_extent = (
                self._item_extent if self._expandable_content is None else None
            )
            if self._scroll_height or self._expand_table:
                lv = self._listview
                if lv is None:
                    lv = ft.ListView(spacing=0)
                    if self._scroll_height:
                        lv.height = self._scroll_height
                    else:
                        lv.expand = True
                    self._listview = lv
                lv.item_extent = item_extent
                lv.controls = data_rows
                data_content = lv
            else:
                data_content = ft.Column(data_rows, spacing=0)

        self._data_content = data_content
        self._header_host.content = header
        self._data_host.content = data_content
