"""Settings: the server knobs and what they are set to."""

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    TableCellText,
    TableNameText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import ui_database
from app.services.system.models import ComponentStatus


class SettingsTab(ft.Container):
    """Settings tab for PostgreSQL or SQLite PRAGMA settings."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = database_component.metadata or {}

        columns = [
            DataTableColumn("Setting"),
            DataTableColumn("Value", width=120),
            DataTableColumn("Category", width=120),
        ]
        rows: list[list[ft.Control]] = [
            [
                TableNameText(row["setting"]),
                TableCellText(row["value"]),
                TableCellText(row["category"]),
            ]
            for row in ui_database.settings(metadata)
        ]

        table = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No settings available",
        )

        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
