"""
Task History Section

Background-worker task history: a thin configuration of the shared
``PaginatedHistorySection`` (status + queue filters, per-queue endpoints,
worker-specific columns and row layout). All filter / pagination / load
machinery is reused from ``history_table``.
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
from app.services.system import ui_worker

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
COL_WIDTH_QUEUE = 90
COL_WIDTH_DURATION = 80
COL_WIDTH_ENQUEUED = 150
COL_WIDTH_STATUS = 80

# Status filter options: (label, api_value, color)
_STATUS_FILTER_OPTIONS: list[FilterOption] = [
    ("All", "all", Theme.Colors.ACCENT),
    ("Completed", "completed", Theme.Colors.SUCCESS),
    ("Failed", "failed", Theme.Colors.ERROR),
    ("Running", "running", Theme.Colors.INFO),
]


def _build_task_row(task: dict[str, str]) -> ExpandableRow:
    """Build a table row for a single task record."""
    status = task.get("status", "unknown")
    status_label, color_name = ui_worker.task_status(status)
    has_error = status == "failed" and task.get("error")
    status_color = Theme.Colors.semantic(color_name)

    cells = [
        build_status_dot_cell(status_color),
        PrimaryText(
            task.get("name", "unknown"),
            size=Theme.Typography.BODY,
            overflow=ft.TextOverflow.ELLIPSIS,
        ),
        BodyText(task.get("queue", "—"), text_align=ft.TextAlign.CENTER),
        BodyText(
            format_duration_ms(task.get("duration_ms")),
            text_align=ft.TextAlign.CENTER,
        ),
        SecondaryText(
            format_relative_time(task.get("enqueued_at")),
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

    description = task.get("description", "")
    if description:
        expanded_items.append(
            ft.Text(
                description,
                size=Theme.Typography.BODY,
                italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT,
            )
        )
        expanded_items.append(ft.Container(height=6))

    if has_error:
        error_text = task.get("error", "")
        expanded_items.append(
            ft.Text(
                "Error Details",
                size=12,
                weight=ft.FontWeight.W_600,
                color=Theme.Colors.ERROR,
            )
        )
        expanded_items.append(ft.Container(height=4))
        expanded_items.append(build_error_detail_block(error_text))
        expanded_items.append(ft.Container(height=4))

    expanded_items.append(
        ft.Row(
            [
                SecondaryText(f"Job ID: {task.get('job_id', '—')}", size=11),
                SecondaryText("|", size=11),
                SecondaryText(
                    f"Started: {format_timestamp(task.get('started_at'))}",
                    size=11,
                ),
                SecondaryText("|", size=11),
                SecondaryText(
                    f"Finished: {format_timestamp(task.get('finished_at'))}",
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


class TaskHistorySection(PaginatedHistorySection):
    """Task history across background-worker queues."""

    def __init__(self, page: ft.Page) -> None:
        queue_names = ["all"]
        try:
            from app.core.config import get_available_queues

            queue_names.extend(get_available_queues())
        except Exception:
            pass

        super().__init__(
            page,
            columns=[
                DataTableColumn("", width=COL_WIDTH_STATUS_ICON),
                DataTableColumn("Task Name"),
                DataTableColumn("Queue", width=COL_WIDTH_QUEUE, alignment="center"),
                DataTableColumn(
                    "Duration", width=COL_WIDTH_DURATION, alignment="center"
                ),
                DataTableColumn(
                    "Enqueued", width=COL_WIDTH_ENQUEUED, alignment="center"
                ),
                DataTableColumn("Status", width=COL_WIDTH_STATUS, alignment="center"),
            ],
            empty_message="No task history available",
            filter_specs={
                "status": FilterSpec(
                    icon=ft.Icons.FILTER_LIST,
                    options=_STATUS_FILTER_OPTIONS,
                    dot_color=Theme.Colors.ACCENT,
                ),
                "queue": FilterSpec(
                    icon=ft.Icons.STACKED_BAR_CHART,
                    options=[
                        ("All" if q == "all" else q, q, Theme.Colors.INFO)
                        for q in queue_names
                    ],
                    dot_color=Theme.Colors.INFO,
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

        api = self.api_client()
        queue = self.filters["queue"].value

        if queue == "all":
            # Fetch from all queues and merge, newest first.
            all_tasks: list[dict[str, Any]] = []
            total = 0
            try:
                from app.core.config import get_available_queues

                queues = get_available_queues()
            except Exception:
                queues = []
            for q in queues:
                data = await api.get(f"/api/v1/tasks/history/{q}", params=params)
                if isinstance(data, dict):
                    all_tasks.extend(data.get("tasks", []))
                    total += data.get("total", 0)
            all_tasks.sort(key=lambda t: t.get("enqueued_at", ""), reverse=True)
            return all_tasks[:limit], total

        data = await api.get(f"/api/v1/tasks/history/{queue}", params=params)
        if isinstance(data, dict):
            return data.get("tasks", []), data.get("total", 0)
        return [], 0

    def build_row(self, record: dict[str, Any]) -> ExpandableRow:
        return _build_task_row(record)
