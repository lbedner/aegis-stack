"""Small conversions the modals share: durations, timestamps, match tests, colours."""

from __future__ import annotations

from collections.abc import Iterable

import flet as ft
from app.components.frontend.controls import (
    StatusDot,
)
from app.components.frontend.theme import AegisTheme as Theme


def format_duration_ms(duration_ms: int | float | str | None) -> str:
    """Format milliseconds to human-readable duration (e.g., '1.2s', '3m 45s')."""
    if not duration_ms:
        return "\u2014"
    try:
        ms = float(duration_ms)
        if ms < 1000:
            return f"{ms:.0f}ms"
        s = ms / 1000
        if s < 60:
            return f"{s:.1f}s"
        m = int(s // 60)
        s = s % 60
        return f"{m}m {s:.0f}s"
    except (ValueError, TypeError):
        return "\u2014"


def format_timestamp(iso_str: str | None) -> str:
    """Format ISO timestamp for display (HH:MM:SS)."""
    if not iso_str:
        return "\u2014"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "\u2014"


def headline_stat_color(cents: int) -> str:
    """Red once a figure goes negative; otherwise the primary text colour.

    Deliberately NOT green-for-positive: when every healthy number is
    coloured, colour stops meaning anything and the one number in trouble
    no longer stands out.
    """
    return Theme.Colors.ERROR if cents < 0 else Theme.Colors.TEXT_PRIMARY


def row_matches(query: str, values: Iterable[object]) -> bool:
    """Does this row match a search box, looking at EVERY column?

    The tabs that hold their whole dataset (Bills & Income, Payees) filter
    in memory, and each of them used to match its name column alone while
    rendering five or six. Searching a category or an account then came
    back empty, which reads as "no such row" rather than "that column is
    not searched".

    Callers pass the same values they render, so the rule stays "if you
    can see it, you can search it" without this needing to know their
    shapes. The register is not a caller: it pages, so it searches
    server-side (``transaction_search_filter``).
    """
    needle = (query or "").strip().casefold()
    if not needle:
        return True
    return any(needle in str(value).casefold() for value in values if value is not None)


def date_cell(
    value: object, control: type[ft.Text] | None = None, *, sort_value: object = None
) -> ft.Control:
    """A human-readable date cell that still sorts chronologically.

    DataTable sorts on a cell's text (controls/data_table.py), so the
    rendered "Aug 19, 2026" would sort alphabetically. ``.data`` is the
    escape hatch ``_cell_text`` falls back to, so the ISO string rides
    along invisibly and the column keeps sorting by date. ``sort_value``
    is for a column that shows one date and sorts in the order of another.
    """
    from app.components.frontend.controls.table import TableCellText
    from app.core.formatting import format_date

    factory = control or TableCellText
    cell = factory(format_date(value))
    cell.data = str(sort_value if sort_value is not None else value or "")
    return cell


def status_dot(label: str, color: str, tooltip: str) -> StatusDot:
    """Status as the house dot: a circle + colored label, no pill
    background. The tooltip carries what the state actually MEANS -
    "Detected" is a question the detector is asking, and a bare word does
    not say so.

    Kept as a name the finance tabs already call; the recipe itself lives
    in ``controls.StatusDot`` so a surface can reach for the control
    directly.
    """
    return StatusDot(label, color, tooltip)


def ledger_amount_color(cents: int) -> str:
    """Colour for a money amount in a TABLE row.

    The opposite of ``headline_stat_color``, on purpose. A ledger is
    mostly spending, so an outflow is the assumption and takes no colour -
    tinting nearly every row points at nothing. Money coming IN is the
    exception, and that is what teal marks.
    """
    return Theme.Colors.SUCCESS if cents > 0 else Theme.Colors.TEXT_PRIMARY
