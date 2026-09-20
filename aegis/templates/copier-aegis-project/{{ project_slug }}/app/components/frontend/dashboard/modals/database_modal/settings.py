"""Settings: the server knobs and what they are set to."""

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    TableCellText,
    TableNameText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus


def _build_setting_row(name: str, value: str | int, category: str) -> list[ft.Control]:
    """Build row cells for a setting."""
    if isinstance(value, bool):
        value_text = "Enabled" if value else "Disabled"
    elif isinstance(value, int | float):
        value_text = f"{value:,}"
    else:
        value_text = str(value)

    return [
        TableNameText(name),
        TableCellText(value_text),
        TableCellText(category),
    ]


class SettingsTab(ft.Container):
    """Settings tab for PostgreSQL or SQLite PRAGMA settings."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = database_component.metadata or {}
        implementation = metadata.get("implementation", "sqlite")

        columns = [
            DataTableColumn("Setting"),
            DataTableColumn("Value", width=120),
            DataTableColumn("Category", width=120),
        ]

        rows: list[list[ft.Control]] = []

        if implementation == "postgresql":
            rows = self._build_postgres_rows(metadata)
        else:
            rows = self._build_sqlite_rows(metadata)

        table = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No settings available",
        )

        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    def _build_postgres_rows(self, metadata: dict) -> list[list[ft.Control]]:
        """Build rows for PostgreSQL settings."""
        pg_settings = metadata.get("pg_settings", {})
        active_connections = metadata.get("active_connections", 0)
        rows: list[list[ft.Control]] = []

        # Connection settings
        if "max_connections" in pg_settings:
            rows.append(
                _build_setting_row(
                    "max_connections", pg_settings["max_connections"], "Connections"
                )
            )
        rows.append(
            _build_setting_row(
                "active_connections", str(active_connections), "Connections"
            )
        )

        # Memory settings
        if "shared_buffers" in pg_settings:
            rows.append(
                _build_setting_row(
                    "shared_buffers", pg_settings["shared_buffers"], "Memory"
                )
            )
        if "work_mem" in pg_settings:
            rows.append(
                _build_setting_row("work_mem", pg_settings["work_mem"], "Memory")
            )
        if "effective_cache_size" in pg_settings:
            rows.append(
                _build_setting_row(
                    "effective_cache_size",
                    pg_settings["effective_cache_size"],
                    "Memory",
                )
            )
        if "maintenance_work_mem" in pg_settings:
            rows.append(
                _build_setting_row(
                    "maintenance_work_mem",
                    pg_settings["maintenance_work_mem"],
                    "Memory",
                )
            )

        # WAL settings
        if "wal_level" in pg_settings:
            rows.append(
                _build_setting_row("wal_level", pg_settings["wal_level"], "WAL")
            )

        return rows

    def _build_sqlite_rows(self, metadata: dict) -> list[list[ft.Control]]:
        """Build rows for SQLite PRAGMA settings."""
        pragma_settings = metadata.get("pragma_settings", {})
        comprehensive_pragma = metadata.get("comprehensive_pragma", {})
        all_pragma = {**pragma_settings, **comprehensive_pragma}
        rows: list[list[ft.Control]] = []

        # Performance settings
        if "cache_size" in all_pragma:
            rows.append(
                _build_setting_row(
                    "cache_size", all_pragma["cache_size"], "Performance"
                )
            )
        if "mmap_size" in all_pragma:
            rows.append(
                _build_setting_row("mmap_size", all_pragma["mmap_size"], "Performance")
            )
        if "temp_store" in all_pragma:
            temp = all_pragma["temp_store"]
            temp_desc = {0: "DEFAULT", 1: "FILE", 2: "MEMORY"}.get(temp, str(temp))
            rows.append(_build_setting_row("temp_store", temp_desc, "Performance"))
        if "busy_timeout" in all_pragma:
            rows.append(
                _build_setting_row(
                    "busy_timeout", f"{all_pragma['busy_timeout']}ms", "Performance"
                )
            )

        # Integrity settings
        if "foreign_keys" in all_pragma:
            rows.append(
                _build_setting_row(
                    "foreign_keys", all_pragma["foreign_keys"], "Integrity"
                )
            )
        if "synchronous" in all_pragma:
            sync = all_pragma["synchronous"]
            sync_desc = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}.get(
                sync, str(sync)
            )
            rows.append(_build_setting_row("synchronous", sync_desc, "Integrity"))
        if "auto_vacuum" in all_pragma:
            auto_vac = all_pragma["auto_vacuum"]
            auto_vac_desc = {0: "NONE", 1: "FULL", 2: "INCREMENTAL"}.get(
                auto_vac, str(auto_vac)
            )
            rows.append(_build_setting_row("auto_vacuum", auto_vac_desc, "Integrity"))

        # Storage settings
        if "journal_mode" in all_pragma:
            rows.append(
                _build_setting_row(
                    "journal_mode", all_pragma["journal_mode"].upper(), "Storage"
                )
            )
        wal_enabled = metadata.get("wal_enabled", False)
        rows.append(_build_setting_row("wal_enabled", wal_enabled, "Storage"))
        if "page_size" in all_pragma:
            rows.append(
                _build_setting_row(
                    "page_size", f"{all_pragma['page_size']} bytes", "Storage"
                )
            )

        # Statistics
        if "page_count" in all_pragma:
            rows.append(
                _build_setting_row("page_count", all_pragma["page_count"], "Statistics")
            )
        if "freelist_count" in all_pragma:
            rows.append(
                _build_setting_row(
                    "freelist_count", all_pragma["freelist_count"], "Statistics"
                )
            )
        if "db_efficiency" in all_pragma:
            rows.append(
                _build_setting_row(
                    "db_efficiency", f"{all_pragma['db_efficiency']:.2f}%", "Statistics"
                )
            )

        return rows
