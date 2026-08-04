"""
Database Detail Modal

Displays comprehensive database information in a tabbed interface:
- Overview: Key metrics and statistics
- Schema: Table details with expandable CREATE TABLE
- Migrations: Migration history with expandable code
- Settings: PostgreSQL or SQLite PRAGMA settings
"""

from datetime import datetime

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    ExpandableDataTable,
    ExpandableRow,
    TableCellText,
    TableNameText,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title, get_database_subtitle

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

# =============================================================================
# Overview Tab
# =============================================================================


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


# =============================================================================
# Schema Tab
# =============================================================================


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

    code_style = ft.TextStyle(
        size=13,
        font_family="Roboto Mono",
        weight=ft.FontWeight.W_400,
        height=1.4,
    )
    codeblock_decoration = ft.BoxDecoration(
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=ft.border_radius.all(8),
    )
    code_theme = "ir-black" if is_dark_mode else "atom-one-light"

    return ft.Markdown(
        f"```sql\n{schema_text}\n```",
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        code_theme=code_theme,
        md_style_sheet=ft.MarkdownStyleSheet(
            code_text_style=code_style,
            codeblock_decoration=codeblock_decoration,
        ),
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


# =============================================================================
# Migrations Tab
# =============================================================================


def _build_migration_expanded_content(
    migration: dict, is_dark_mode: bool
) -> ft.Control:
    """Build expanded content for a migration showing the code."""
    import re

    content = migration.get("content", "# Migration content not available")
    file_path = migration.get("file_path", "Unknown")

    content = re.sub(r"\n\s*\n", "\n", content)

    code_style = ft.TextStyle(
        size=12,
        font_family="Roboto Mono",
        weight=ft.FontWeight.W_400,
        height=1.2,
    )
    codeblock_decoration = ft.BoxDecoration(
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=ft.border_radius.all(8),
    )
    code_theme = "ir-black" if is_dark_mode else "atom-one-light"

    return ft.Column(
        [
            ft.Text(
                file_path, size=11, color=ft.Colors.ON_SURFACE_VARIANT, italic=True
            ),
            ft.Container(height=4),
            ft.Markdown(
                f"```python\n{content}\n```",
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                code_theme=code_theme,
                md_style_sheet=ft.MarkdownStyleSheet(
                    code_text_style=code_style,
                    codeblock_decoration=codeblock_decoration,
                ),
            ),
        ],
        spacing=0,
    )


def _build_migration_row(migration: dict, is_dark_mode: bool) -> ExpandableRow:
    """Build expandable row for a single migration."""
    revision = migration.get("revision", "Unknown")
    description = migration.get("description", "No description")
    is_current = migration.get("is_current", False)
    file_mtime = migration.get("file_mtime", 0)

    try:
        dt = datetime.fromtimestamp(file_mtime)
        date_str = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError, TypeError):
        date_str = "Unknown"

    short_revision = revision[:12] if len(revision) > 12 else revision
    revision_text = f"{short_revision} (current)" if is_current else short_revision
    revision_color = Theme.Colors.SUCCESS if is_current else None

    cells = [
        TableNameText(revision_text, color=revision_color),
        TableCellText(date_str),
        TableCellText(description),
    ]

    return ExpandableRow(
        cells=cells,
        expanded_content=_build_migration_expanded_content(migration, is_dark_mode),
    )


class MigrationsTab(ft.Container):
    """Migrations tab with expandable migration history."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = database_component.metadata or {}
        migrations = metadata.get("migrations", [])
        is_dark_mode = page.theme_mode == ft.ThemeMode.DARK

        columns = [
            DataTableColumn("Revision", width=140),
            DataTableColumn("Date", width=130),
            DataTableColumn("Description"),
        ]

        rows = [_build_migration_row(m, is_dark_mode) for m in migrations]

        table = ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No migrations found",
        )

        self.content = ft.Column([table], scroll=ft.ScrollMode.AUTO)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True


# =============================================================================
# Settings Tab
# =============================================================================


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


# =============================================================================
# Main Dialog
# =============================================================================


class DatabaseDetailDialog(BaseDetailPopup):
    """Database detail popup with tabbed interface."""

    def __init__(
        self,
        database_component: ComponentStatus,
        page: ft.Page,
    ) -> None:
        metadata = database_component.metadata or {}
        subtitle = get_database_subtitle(metadata)

        # Build tabs
        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=OverviewTab(database_component, page)),
                ft.Tab(text="Schema", content=SchemaTab(database_component, page)),
                ft.Tab(
                    text="Migrations", content=MigrationsTab(database_component, page)
                ),
                ft.Tab(text="Settings", content=SettingsTab(database_component, page)),
            ],
            expand=True,
        )

        # Initialize base popup with tabs
        super().__init__(
            page=page,
            component_data=database_component,
            title_text=get_component_title("database"),
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=1000,
            height=700,
            status_detail=get_status_detail(database_component),
        )
