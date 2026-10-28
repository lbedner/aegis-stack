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
# The last column, a row's buttons (``actions``).
ACTIONS_WIDTH = 60


def columns_of(pairs: tuple[tuple[str, str], ...]) -> list[Column]:
    """A ``ui_*`` module's ``(key, label)`` pairs as columns, each filling."""
    return [(label, key, None) for key, label in pairs]


class TableTab(ft.Container):
    """``rows`` as a table; the first column reads as each row's name, and
    ``actions`` (a row's buttons) adds a last column, as htmx's
    ``data_table`` does. ``color_of(row, key)`` colours a cell (a figure
    past its threshold); None leaves it plain. ``detail(row)`` is what a
    row opens to, built when it is first opened."""

    def __init__(
        self,
        rows: list[dict[str, str]],
        columns: list[Column],
        empty: str,
        actions: Callable[[dict[str, str]], ft.Control] | None = None,
        color_of: Callable[[dict[str, str], str], str | None] | None = None,
        detail: Callable[[dict[str, str]], ft.Control] | None = None,
    ) -> None:
        super().__init__()
        self._columns, self._actions = columns, actions
        self._color_of, self._detail = color_of, detail
        headers = [DataTableColumn(header, width=width) for header, _, width in columns]
        self._table = DataTable(
            columns=[*headers, DataTableColumn("", width=ACTIONS_WIDTH)] if actions else headers,
            rows=self._cells(rows),
            row_padding=6,
            empty_message=empty,
            expandable_content=self._opened(rows),
        )
        self.content = ft.Column([self._table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    def show(self, rows: list[dict[str, str]]) -> None:
        """New ``rows`` in place: the table, its scroll and the rows open
        stay (a row is known by its place)."""
        self._table.set_rows(
            self._cells(rows),
            expandable_content=self._opened(rows),
            keep_expanded=True,
        )

    def _cells(self, rows: list[dict[str, str]]) -> list[list[ft.Control]]:
        return [
            [
                _name(row, key) if index == 0 else _cell(row, key, self._color_of)
                for index, (_, key, _) in enumerate(self._columns)
            ]
            + ([self._actions(row)] if self._actions else [])
            for row in rows
        ]

    def _opened(self, rows: list[dict[str, str]]) -> Callable[[int], ft.Control] | None:
        detail = self._detail
        return (lambda index: detail(rows[index])) if detail else None


def _name(row: dict[str, str], key: str) -> ft.Control:
    """The row's name; a row's part (``child``, as htmx's ``data_table``
    indents it) sits indented under the row it belongs to."""
    name = TableNameText(row[key])
    if not row.get("child"):
        return name
    return ft.Container(name, padding=ft.padding.only(left=Theme.Spacing.MD))


def _cell(
    row: dict[str, str],
    key: str,
    color_of: Callable[[dict[str, str], str], str | None] | None,
) -> ft.Control:
    color = color_of(row, key) if color_of else None
    return TableCellText(row[key], **({"color": color} if color else {}))
