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
from app.services.system.models import ComponentStatus


def _build_table_expanded_content(table_schema: dict, is_dark_mode: bool) -> ft.Control:
    """Build expanded content showing table schema as CREATE TABLE SQL."""
    name = table_schema.get("name", "Unknown")
    columns = table_schema.get("columns", [])
    indexes = table_schema.get("indexes", [])
    foreign_keys = table_schema.get("foreign_keys", [])

    lines: list[str] = []
    lines.append(f"CREATE TABLE IF NOT EXISTS {name} (")

    col_definitions: list[str] = []
    pk_columns: list[str] = []

    for col in columns:
        col_name = col.get("name", "?")
        col_type = col.get("type", "?")
        nullable = col.get("nullable", True)
        pk = col.get("primary_key", False)

        col_def = f"    {col_name} {col_type}"
        if not nullable:
            col_def += " NOT NULL"
        col_definitions.append(col_def)

        if pk:
            pk_columns.append(col_name)

    if col_definitions:
        for i, col_def in enumerate(col_definitions):
            if i < len(col_definitions) - 1 or pk_columns:
                lines.append(col_def + ",")
            else:
                lines.append(col_def)

    if pk_columns:
        lines.append(f"    PRIMARY KEY ({', '.join(pk_columns)})")

    lines.append(");")

    if indexes:
        lines.append("")
        lines.append("-- Indexes")
        for idx in indexes:
            idx_name = idx.get("name", "?")
            idx_cols = idx.get("columns", [])
            unique = idx.get("unique", False)
            unique_str = "UNIQUE " if unique else ""
            cols_str = ", ".join(idx_cols)
            lines.append(f"CREATE {unique_str}INDEX {idx_name} ON {name} ({cols_str});")

    if foreign_keys:
        lines.append("")
        lines.append("-- Foreign Keys")
        for fk in foreign_keys:
            fk_col = fk.get("column", "?")
            ref_table = fk.get("referred_table", "?")
            ref_col = fk.get("referred_column", "?")
            lines.append(f"-- {fk_col} REFERENCES {ref_table}({ref_col})")

    schema_text = "\n".join(lines)

    # The fences are for display; the clipboard gets the statement.
    return copyable_markdown(
        f"```sql\n{schema_text}\n```",
        copy_text=schema_text,
        dark=is_dark_mode,
    )


def _build_table_row(table_schema: dict, is_dark_mode: bool) -> ExpandableRow:
    """Build expandable row for a single table."""
    name = table_schema.get("name", "Unknown")
    rows = table_schema.get("rows", 0)
    columns = table_schema.get("columns", [])
    indexes = table_schema.get("indexes", [])
    foreign_keys = table_schema.get("foreign_keys", [])

    cells = [
        TableNameText(name),
        TableCellText(f"{rows:,}"),
        TableCellText(str(len(columns))),
        TableCellText(str(len(indexes))),
        TableCellText(str(len(foreign_keys))),
    ]

    return ExpandableRow(
        cells=cells,
        expanded_content=_build_table_expanded_content(table_schema, is_dark_mode),
    )


class SchemaTab(ft.Container):
    """Schema tab with expandable table details."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = database_component.metadata or {}
        table_schemas = metadata.get("table_schemas", [])
        is_dark_mode = page.theme_mode == ft.ThemeMode.DARK

        columns = [
            DataTableColumn("Table"),
            DataTableColumn("Rows", width=80, alignment="right"),
            DataTableColumn("Columns", width=70, alignment="right"),
            DataTableColumn("Indexes", width=70, alignment="right"),
            DataTableColumn("FKs", width=50, alignment="right"),
        ]

        rows = [_build_table_row(t, is_dark_mode) for t in table_schemas]

        table = ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No tables found",
        )

        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
