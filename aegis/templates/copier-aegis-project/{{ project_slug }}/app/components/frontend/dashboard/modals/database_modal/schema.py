"""Schema: the tables, expandable to their columns."""

import flet as ft

from app.components.frontend.controls import (
    DataTableColumn,
    ExpandableDataTable,
    ExpandableRow,
    TableCellText,
    TableNameText,
)
from app.components.frontend.controls.markdown import copyable_markdown
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import ui_database
from app.services.system.models import ComponentStatus


def _build_table_row(table: dict, is_dark_mode: bool) -> ExpandableRow:
    """One table: its counts, expanding to its CREATE TABLE statement."""
    cells = [
        TableNameText(table["name"]),
        TableCellText(f"{table['rows']:,}"),
        TableCellText(str(table["columns"])),
        TableCellText(str(table["indexes"])),
        TableCellText(str(table["foreign_keys"])),
    ]
    # The fences are for display; the clipboard gets the statement.
    return ExpandableRow(
        cells=cells,
        expanded_content=copyable_markdown(
            f"```sql\n{table['sql']}\n```", copy_text=table["sql"], dark=is_dark_mode
        ),
    )


class SchemaTab(ft.Container):
    """Schema tab with expandable table details."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = database_component.metadata or {}
        is_dark_mode = page.theme_mode == ft.ThemeMode.DARK

        columns = [
            DataTableColumn("Table"),
            DataTableColumn("Rows", width=80, alignment="right"),
            DataTableColumn("Columns", width=70, alignment="right"),
            DataTableColumn("Indexes", width=70, alignment="right"),
            DataTableColumn("FKs", width=50, alignment="right"),
        ]

        rows = [_build_table_row(t, is_dark_mode) for t in ui_database.tables(metadata)]

        table = ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No tables found",
        )

        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
