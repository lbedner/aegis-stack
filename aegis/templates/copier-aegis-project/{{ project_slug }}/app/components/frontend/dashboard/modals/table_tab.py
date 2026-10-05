"""A tab or section that is one table of rows (``ui_database``, ``ui_runtime``)."""

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    TableCellText,
    TableNameText,
)
from app.components.frontend.theme import AegisTheme as Theme

# A column: its header, the row key it shows, and a fixed width (None fills).
Column = tuple[str, str, int | None]


def columns_of(pairs: tuple[tuple[str, str], ...]) -> list[Column]:
    """A ``ui_*`` module's ``(key, label)`` pairs as columns, each filling."""
    return [(label, key, None) for key, label in pairs]


class TableTab(ft.Container):
    """``rows`` as a table; the first column reads as each row's name, and
    ``actions`` (a row's buttons) adds a last column, as htmx's
    ``data_table`` does. ``color_of(row, key)`` colours a cell (a figure
    past its threshold); None leaves it plain."""

    def __init__(
        self,
        rows: list[dict[str, str]],
        columns: list[Column],
        empty: str,
        actions: Callable[[dict[str, str]], ft.Control] | None = None,
        color_of: Callable[[dict[str, str], str], str | None] | None = None,
    ) -> None:
        super().__init__()
        headers = [DataTableColumn(header, width=width) for header, _, width in columns]
        table = DataTable(
            columns=[*headers, DataTableColumn("", width=60)] if actions else headers,
            rows=[
                [
                    TableNameText(row[key]) if index == 0 else _cell(row, key, color_of)
                    for index, (_, key, _) in enumerate(columns)
                ]
                + ([actions(row)] if actions else [])
                for row in rows
            ],
            row_padding=6,
            empty_message=empty,
        )
        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True


def _cell(
    row: dict[str, str],
    key: str,
    color_of: Callable[[dict[str, str], str], str | None] | None,
) -> ft.Control:
    color = color_of(row, key) if color_of else None
    return TableCellText(row[key], **({"color": color} if color else {}))
