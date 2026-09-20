"""Overview: what engine this is and how it is holding up."""

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    TableCellText,
    TableNameText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import MetricCard


class OverviewTab(ft.Container):
    """Overview tab with key metrics and statistics."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = database_component.metadata or {}
        implementation = metadata.get("implementation", "sqlite")

        # Extract metrics
        table_count = metadata.get("table_count", 0)
        total_rows = metadata.get("total_rows", 0)

        if implementation == "postgresql":
            db_size = metadata.get("database_size_human", "Unknown")
            # Get connections info
            pg_settings = metadata.get("pg_settings", {})
            active_connections = metadata.get("active_connections", 0)
            max_connections = pg_settings.get("max_connections", "?")
            connections_value = f"{active_connections} / {max_connections}"
        else:
            db_size = metadata.get("file_size_human", "0 B")
            # SQLite: show pool size (no real connections concept)
            pool_size = metadata.get("connection_pool_size", 1)
            connections_value = str(pool_size)

        # Metric cards row
        metric_cards = ft.Row(
            [
                MetricCard("Total Tables", str(table_count), Theme.Colors.INFO),
                MetricCard("Total Rows", f"{total_rows:,}", Theme.Colors.SUCCESS),
                MetricCard("Database Size", db_size, Theme.Colors.INFO),
                MetricCard("Connections", connections_value, Theme.Colors.INFO),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
        )

        # Statistics section
        db_url = metadata.get("url", "Unknown")
        self.db_url_local = self._convert_to_localhost(db_url)
        pool_size = metadata.get("connection_pool_size", 0)
        total_indexes = metadata.get("total_indexes", 0)
        total_foreign_keys = metadata.get("total_foreign_keys", 0)
        largest_table = metadata.get("largest_table", {})
        largest_table_name = largest_table.get("name", "None")
        largest_table_rows = largest_table.get("rows", 0)

        # Statistics table
        stats_columns = [
            DataTableColumn("Statistic"),
            DataTableColumn("Value", width=450),
        ]

        # URL row with copy button
        url_row = [
            TableNameText("Database URL"),
            ft.Row(
                [
                    ft.GestureDetector(
                        content=ft.Text(
                            self.db_url_local,
                            size=11,
                            color=Theme.Colors.INFO,
                            style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                        ),
                        on_tap=self._copy_url,
                        mouse_cursor=ft.MouseCursor.CLICK,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.COPY,
                        icon_size=14,
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        tooltip="Copy URL",
                        on_click=self._copy_url,
                    ),
                ],
                spacing=4,
            ),
        ]

        stats_rows: list[list[ft.Control]] = [
            url_row,
            [TableNameText("Connection Pool Size"), TableCellText(str(pool_size))],
            [TableNameText("Total Indexes"), TableCellText(str(total_indexes))],
            [
                TableNameText("Total Foreign Keys"),
                TableCellText(str(total_foreign_keys)),
            ],
            [
                TableNameText("Largest Table"),
                TableCellText(f"{largest_table_name} ({largest_table_rows:,} rows)"),
            ],
        ]

        stats_table = DataTable(
            columns=stats_columns,
            rows=stats_rows,
            row_padding=6,
            empty_message="No statistics available",
        )

        self.content = ft.Column(
            [
                metric_cards,
                ft.Container(height=Theme.Spacing.LG),
                stats_table,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    def _convert_to_localhost(self, url: str) -> str:
        """Convert docker service names to localhost in URL."""
        replacements = {
            "@db:": "@localhost:",
            "@postgres:": "@localhost:",
            "@postgresql:": "@localhost:",
            "@database:": "@localhost:",
            "@redis:": "@localhost:",
        }
        result = url
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result

    def _copy_url(self, _e: ft.ControlEvent) -> None:
        """Copy database URL to clipboard."""
        self.page.set_clipboard(self.db_url_local)
        self.page.open(ft.SnackBar(content=ft.Text("URL copied to clipboard")))
        self.page.update()
