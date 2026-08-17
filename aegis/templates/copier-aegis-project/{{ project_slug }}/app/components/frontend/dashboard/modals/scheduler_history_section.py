"""
Scheduler History Section

Scheduled-job execution history: a thin configuration of the shared
``PaginatedHistorySection`` (status filter, one endpoint, scheduler-specific
columns and row layout). All filter / pagination / load machinery is reused
from ``history_table``.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTableColumn,
    ExpandableRow,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time

from .history_table import (
    FilterOption,
    FilterSpec,
    PaginatedHistorySection,
    build_error_detail_block,
    build_status_dot_cell,
)
from .modal_sections import format_duration_ms, format_timestamp

# Column widths
COL_WIDTH_STATUS_ICON = 30
COL_WIDTH_DURATION = 80
COL_WIDTH_STARTED = 150
COL_WIDTH_STATUS = 80

# Status display: api value -> label (the dot color comes from _STATUS_COLORS)
_STATUS_DISPLAY: dict[str, str] = {
    "running": "Running",
    "success": "Success",
    "failed": "Failed",
    "missed": "Missed",
}

_STATUS_FILTER_OPTIONS: list[FilterOption] = [
    ("All", "all", Theme.Colors.ACCENT),
    ("Success", "success", Theme.Colors.SUCCESS),
    ("Failed", "failed", Theme.Colors.ERROR),
    ("Running", "running", Theme.Colors.INFO),
    ("Missed", "missed", Theme.Colors.WARNING),
]

_STATUS_COLORS: dict[str, str] = {
    "success": Theme.Colors.SUCCESS,
    "failed": Theme.Colors.ERROR,
    "running": Theme.Colors.INFO,
    "missed": Theme.Colors.WARNING,
}


def _build_execution_row(record: dict[str, Any]) -> ExpandableRow:
    """Build a table row for a single execution record."""
    status = record.get("status", "unknown")
    status_label = _STATUS_DISPLAY.get(status, status)
    has_error = status == "failed" and record.get("error_message")
    status_color = _STATUS_COLORS.get(status, ft.Colors.ON_SURFACE_VARIANT)

    cells = [
        build_status_dot_cell(status_color),
        PrimaryText(
            record.get("job_name") or record.get("job_id", "unknown"),
            size=Theme.Typography.BODY,
            overflow=ft.TextOverflow.ELLIPSIS,
        ),
        BodyText(
            format_duration_ms(record.get("duration_ms")),
            text_align=ft.TextAlign.CENTER,
        ),
        SecondaryText(
            format_relative_time(record.get("started_at")),
            text_align=ft.TextAlign.CENTER,
        ),
        SecondaryText(
            status_label,
            color=status_color,
            weight=Theme.Typography.WEIGHT_SEMIBOLD,
            text_align=ft.TextAlign.CENTER,
        ),
    ]

    expanded_items: list[ft.Control] = []
    if has_error:
        expanded_items.append(
            ft.Text(
                "Error Details",
                size=12,
                weight=ft.FontWeight.W_600,
                color=Theme.Colors.ERROR,
            )
        )
        expanded_items.append(ft.Container(height=4))
        expanded_items.append(build_error_detail_block(record.get("error_message", "")))
        expanded_items.append(ft.Container(height=4))

    expanded_items.append(
        ft.Row(
            [
                SecondaryText(f"Job ID: {record.get('job_id', '—')}", size=11),
                SecondaryText("|", size=11),
                SecondaryText(
                    f"Scheduled: {format_timestamp(record.get('scheduled_run_time'))}",
                    size=11,
                ),
                SecondaryText("|", size=11),
                SecondaryText(
                    f"Finished: {format_timestamp(record.get('finished_at'))}",
                    size=11,
                ),
            ],
            spacing=8,
        )
    )

    return ExpandableRow(
        cells=cells,
        expanded_content=ft.Container(
            content=ft.Column(expanded_items, spacing=2),
            padding=ft.padding.all(8),
        ),
    )


class SchedulerHistorySection(PaginatedHistorySection):
    """Execution history for scheduled jobs."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(
            page,
            columns=[
                DataTableColumn("", width=COL_WIDTH_STATUS_ICON),
                DataTableColumn("Job"),
                DataTableColumn(
                    "Duration", width=COL_WIDTH_DURATION, alignment="center"
                ),
                DataTableColumn("Started", width=COL_WIDTH_STARTED, alignment="center"),
                DataTableColumn("Status", width=COL_WIDTH_STATUS, alignment="center"),
            ],
            empty_message="No execution history available",
            filter_specs={
                "status": FilterSpec(
                    icon=ft.Icons.FILTER_LIST,
                    options=_STATUS_FILTER_OPTIONS,
                    dot_color=Theme.Colors.ACCENT,
                ),
            },
        )

    async def fetch(self, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, str | int] = {
            "offset": offset,
            "limit": limit,
            "order": "desc",
        }
        status = self.filters["status"].value
        if status != "all":
            params["status"] = status

        data = await self.api_client().get(
            "/api/v1/scheduler/executions", params=params
        )
        if isinstance(data, dict):
            return data.get("executions", []), data.get("total", 0)
        return [], 0

    def build_row(self, record: dict[str, Any]) -> ExpandableRow:
        return _build_execution_row(record)
