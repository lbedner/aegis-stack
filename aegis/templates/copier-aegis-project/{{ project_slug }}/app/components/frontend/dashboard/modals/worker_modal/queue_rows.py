"""One queue's row in the health table, and the numbers behind it.

Four things that belong together: the thresholds that decide whether a
queue reads Online, Degraded or Failing; the computation that applies
them; the row that renders the result; and the panel that row expands
into. ``QueueHealthSection`` calls the last two and nothing else calls
any of them.
"""

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    ExpandableRow,
    PrimaryText,
    SecondaryText,
    status_dot,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.components.worker.registry import (
    get_queue_metadata,
)
from app.services.system.models import ComponentStatus

# Worker health status thresholds
FAILURE_RATE_CRITICAL_THRESHOLD = 20  # % - Red status (failing)


FAILURE_RATE_WARNING_THRESHOLD = 5  # % - Yellow status (degraded)


SUCCESS_RATE_HEALTHY_THRESHOLD = 95  # % - Green display


SUCCESS_RATE_WARNING_THRESHOLD = 80  # % - Yellow display


def _build_queue_expanded_content(queue_name: str) -> ft.Control:
    """Build expanded content showing registered functions for a queue.

    Args:
        queue_name: Name of the queue (e.g., 'system', 'load_test')

    Returns:
        Column with queue description and registered functions in table format
    """
    try:
        metadata = get_queue_metadata(queue_name)
        description = metadata.get("description", "")
        functions = metadata.get("functions", [])
        max_jobs = metadata.get("max_jobs", 10)
        timeout = metadata.get("timeout", 300)
    except Exception:
        description = f"Queue: {queue_name}"
        functions = []
        max_jobs = 10
        timeout = 300

    content: list[ft.Control] = []

    # Description on top with italic styling
    if description:
        content.append(
            ft.Text(
                description,
                size=Theme.Typography.BODY,
                italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT,
            )
        )
        content.append(ft.Container(height=Theme.Spacing.SM))

    # Registered functions in a mini table
    if functions:
        # Table header
        header_style = ft.TextStyle(
            size=11,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        task_header = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Text("Task", style=header_style),
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Text("Status", style=header_style),
                        width=70,
                        alignment=ft.alignment.center_right,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.padding.only(bottom=6),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        # Task rows
        task_rows = [task_header]
        cell_style = ft.TextStyle(size=12, color=ft.Colors.ON_SURFACE)

        for func in functions:
            task_row = ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(func, style=cell_style),
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(
                                "Registered",
                                size=10,
                                color=Theme.Colors.SUCCESS,
                                weight=ft.FontWeight.W_500,
                            ),
                            width=70,
                            alignment=ft.alignment.center_right,
                        ),
                    ],
                    spacing=8,
                ),
                padding=ft.padding.symmetric(vertical=4),
            )
            task_rows.append(task_row)

        # Wrap in a styled container
        tasks_table = ft.Container(
            content=ft.Column(task_rows, spacing=0),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            border_radius=6,
            border=ft.border.all(1, ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE)),
            padding=ft.padding.all(10),
        )
        content.append(tasks_table)
    else:
        content.append(
            SecondaryText("No tasks registered", size=Theme.Typography.BODY_SMALL)
        )

    # Config info row
    content.append(ft.Container(height=Theme.Spacing.SM))
    content.append(
        ft.Row(
            [
                SecondaryText(f"Concurrency: {max_jobs}", size=11),
                SecondaryText("|", size=11),
                SecondaryText(f"Timeout: {timeout}s", size=11),
            ],
            spacing=8,
        )
    )

    return ft.Column(content, spacing=4)


def _compute_queue_values(
    queue_component: ComponentStatus,
) -> dict[str, str | float | None]:
    """Compute display values for a queue health row.

    Returns dict with keys: status_color, status_text,
    queued_jobs, jobs_ongoing, jobs_completed, jobs_failed,
    success_rate, rate_color.
    """
    metadata = queue_component.metadata or {}
    worker_alive = metadata.get("worker_alive", False)
    queued_jobs = metadata.get("queued_jobs", 0)
    jobs_ongoing = metadata.get("jobs_ongoing", 0)
    jobs_completed = metadata.get("jobs_completed", 0)
    jobs_failed = metadata.get("jobs_failed", 0)
    failure_rate = metadata.get("failure_rate_percent", 0.0)
    has_job_history = (jobs_completed + jobs_failed) > 0

    # Determine status icon and color (matching card behavior)
    message = queue_component.message or ""
    if not worker_alive:
        if "no functions" in message.lower():
            # No tasks defined
            status_color = ft.Colors.GREY_600
            status_text = "No Tasks"
        else:
            # Offline - problem
            status_color = Theme.Colors.ERROR
            status_text = "Offline"
    elif failure_rate > FAILURE_RATE_CRITICAL_THRESHOLD:
        # Failing
        status_color = Theme.Colors.ERROR
        status_text = "Failing"
    elif failure_rate > FAILURE_RATE_WARNING_THRESHOLD:
        # Degraded
        status_color = Theme.Colors.WARNING
        status_text = "Degraded"
    elif jobs_ongoing > 0:
        # Active - processing
        status_color = Theme.Colors.INFO
        status_text = "Active"
    else:
        # Healthy
        status_color = Theme.Colors.SUCCESS
        status_text = "Online"

    # Success rate display with color coding
    success_rate: float | None = (
        (100 - failure_rate) if (worker_alive and has_job_history) else None
    )
    if success_rate is None:
        rate_color = ft.Colors.ON_SURFACE_VARIANT
    elif success_rate >= SUCCESS_RATE_HEALTHY_THRESHOLD:
        rate_color = Theme.Colors.SUCCESS
    elif success_rate >= SUCCESS_RATE_WARNING_THRESHOLD:
        rate_color = Theme.Colors.WARNING
    else:
        rate_color = Theme.Colors.ERROR

    return {
        "status_color": status_color,
        "status_text": status_text,
        "queued_jobs": queued_jobs,
        "jobs_ongoing": jobs_ongoing,
        "jobs_completed": jobs_completed,
        "jobs_failed": jobs_failed,
        "success_rate": success_rate,
        "rate_color": rate_color,
    }


def _format_eta(seconds: float) -> str:
    """Format an ETA in seconds to a human-readable string."""
    if seconds < 1:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _build_queue_health_row(queue_component: ComponentStatus) -> ExpandableRow:
    """Build row cells for a single queue health status.

    Args:
        queue_component: ComponentStatus for a single queue

    Returns:
        ExpandableRow with controls for each column
    """
    queue_name = queue_component.name
    vals = _compute_queue_values(queue_component)
    status_color = str(vals["status_color"])

    cells = [
        ft.Container(
            content=status_dot(status_color),
            alignment=ft.alignment.center,
        ),
        PrimaryText(queue_name, size=Theme.Typography.BODY),
        BodyText(str(vals["queued_jobs"]), text_align=ft.TextAlign.CENTER),
        BodyText(str(vals["jobs_ongoing"]), text_align=ft.TextAlign.CENTER),
        BodyText(str(vals["jobs_completed"]), text_align=ft.TextAlign.CENTER),
        BodyText(str(vals["jobs_failed"]), text_align=ft.TextAlign.CENTER),
        SecondaryText(
            f"{vals['success_rate']:.1f}%"
            if vals["success_rate"] is not None
            else "N/A",
            color=vals["rate_color"],
            weight=Theme.Typography.WEIGHT_SEMIBOLD,
            text_align=ft.TextAlign.CENTER,
        ),
        SecondaryText(
            "—",
            color=ft.Colors.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
        ),
        SecondaryText(
            "—",
            color=ft.Colors.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
        ),
        SecondaryText(
            vals["status_text"],
            color=vals["status_color"],
            weight=Theme.Typography.WEIGHT_SEMIBOLD,
            text_align=ft.TextAlign.CENTER,
        ),
    ]

    return ExpandableRow(
        cells=cells,
        expanded_content=_build_queue_expanded_content(queue_name),
    )
