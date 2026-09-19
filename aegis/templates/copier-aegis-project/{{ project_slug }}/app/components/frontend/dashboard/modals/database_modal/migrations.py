"""Migrations: what has been applied, and what it did."""

from datetime import datetime

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


def _build_migration_expanded_content(
    migration: dict, is_dark_mode: bool
) -> ft.Control:
    """Build expanded content for a migration showing the code."""
    import re

    content = migration.get("content", "# Migration content not available")
    file_path = migration.get("file_path", "Unknown")

    content = re.sub(r"\n\s*\n", "\n", content)

    return ft.Column(
        [
            ft.Text(
                file_path, size=11, color=ft.Colors.ON_SURFACE_VARIANT, italic=True
            ),
            ft.Container(height=4),
            copyable_markdown(
                f"```python\n{content}\n```",
                copy_text=content,
                dark=is_dark_mode,
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
