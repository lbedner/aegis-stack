"""A tab or section that is one table of rows (``ui_database``, ``ui_runtime``)."""

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


class TableTab(ft.Container):
    """``rows`` as a table; the first column reads as each row's name."""

    def __init__(
        self, rows: list[dict[str, str]], columns: list[Column], empty: str
    ) -> None:
        super().__init__()
        table = DataTable(
            columns=[
                DataTableColumn(header, width=width) for header, _, width in columns
            ],
            rows=[
                [
                    (TableNameText if index == 0 else TableCellText)(row[key])
                    for index, (_, key, _) in enumerate(columns)
                ]
                for row in rows
            ],
            row_padding=6,
            empty_message=empty,
        )
        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
