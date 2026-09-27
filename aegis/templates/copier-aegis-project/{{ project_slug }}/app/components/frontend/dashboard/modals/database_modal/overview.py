"""Overview: what engine this is and how it is holding up."""

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

from ..modal_sections import MetricCard


class OverviewTab(ft.Container):
    """Overview tab with key metrics and statistics."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = database_component.metadata or {}

        figures = ui_database.overview(metadata)

        # Metric cards row
        metric_cards = ft.Row(
            [
                MetricCard("Total Tables", figures["tables"], Theme.Colors.INFO),
                MetricCard("Total Rows", figures["rows"], Theme.Colors.SUCCESS),
                MetricCard("Database Size", figures["size"], Theme.Colors.INFO),
                MetricCard("Connections", figures["connections"], Theme.Colors.INFO),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
        )

        # Statistics section. The URL keeps its password: it is what the
        # copy button puts on the clipboard.
        self.db_url_local = ui_database.display_url(
            str(metadata.get("url", "Unknown")), hide_password=False
        )

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
            [
                TableNameText("Connection Pool Size"),
                TableCellText(figures["pool_size"]),
            ],
            [TableNameText("Total Indexes"), TableCellText(figures["indexes"])],
            [
                TableNameText("Total Foreign Keys"),
                TableCellText(figures["foreign_keys"]),
            ],
            [TableNameText("Largest Table"), TableCellText(figures["largest"])],
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

    def _copy_url(self, _e: ft.ControlEvent) -> None:
        """Copy database URL to clipboard."""
        self.page.set_clipboard(self.db_url_local)
        self.page.open(ft.SnackBar(content=ft.Text("URL copied to clipboard")))
        self.page.update()
