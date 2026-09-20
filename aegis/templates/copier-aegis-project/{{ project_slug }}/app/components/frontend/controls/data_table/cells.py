"""One cell: its text, its sort key, its styling and its box.

Shared by the plain and expandable tables, and by every panel that
builds a cell of its own - which is why ``cell_text`` is public: a
builder stamps ``.data`` precisely because this is what reads it.
"""

from dataclasses import dataclass
from typing import Any, Literal

import flet as ft

from app.components.frontend.controls.text import BodyText, PrimaryText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

# Distinguishes "not passed" from an explicit None in set_rows.
_UNSET: Any = object()


# Cell texts that mean "no value" - they sort after everything real.
_BLANK_CELL_TEXTS = frozenset({"", "—", "-", "–"})


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


def cell_text(cell: Any) -> str | None:
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
    text = cell_text(cell)
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
    "selectable": False,  # the enclosing surface owns selection
}


def style_cell(value: Any, style: str | None) -> ft.Control:
    """Apply a column's style to one cell value: controls pass through,
    everything else becomes styled text.

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
