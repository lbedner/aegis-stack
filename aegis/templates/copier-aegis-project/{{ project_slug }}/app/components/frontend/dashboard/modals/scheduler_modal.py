"""
Scheduler Detail Modal

Displays comprehensive scheduler component information using composition.
Each section is self-contained and can be reused and tested independently.
"""

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    DataTableColumn,
    ExpandableDataTable,
    ExpandableRow,
    SecondaryText,
    TableCellText,
    TableNameText,
    status_dot,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import (
    format_next_run_time,
    format_schedule_human_readable,
    get_status_detail,
)
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard
from .scheduler_history_section import SchedulerHistorySection


class OverviewSection(ft.Container):
    """Overview section showing key scheduler metrics."""

    def __init__(self, metadata: dict) -> None:
        """
        Initialize overview section.

        Args:
            metadata: Component metadata containing task counts
        """
        super().__init__()

        total_tasks = metadata.get("total_tasks", 0)
        active_tasks = metadata.get("active_tasks", 0)
        paused_tasks = metadata.get("paused_tasks", 0)

        # Create metric cards directly
        self.content = ft.Row(
            [
                MetricCard(
                    "Total Tasks",
                    str(total_tasks),
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Active Tasks",
                    str(active_tasks),
                    Theme.Colors.SUCCESS,
                ),
                MetricCard(
                    "Paused Tasks",
                    str(paused_tasks),
                    Theme.Colors.WARNING,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


def _build_job_expanded_content(task: dict, page: ft.Page) -> ft.Control:
    """Build expanded content for a scheduled job."""
    function = task.get("function", "Unknown")
    description = task.get("description")
    job_id = task.get("id", task.get("job_id", "Unknown"))
    job_name = task.get("name", job_id)

    content: list[ft.Control] = []

    if description:
        content.append(
            ft.Text(
                description,
                size=Theme.Typography.BODY,
                italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT,
            )
        )

    content.append(
        SecondaryText(f"Function: {function}", size=Theme.Typography.BODY_SMALL)
    )
    content.append(ft.Container(height=Theme.Spacing.MD))

    async def _on_run_click() -> None:
        async def _confirm() -> None:
            await _trigger_job(page, job_id)

        ConfirmDialog(
            page=page,
            title="Run Job Now",
            message=f"Run '{job_name}' now?",
            confirm_text="Run",
            on_confirm=_confirm,
        ).show()

    content.append(
        ft.Row(
            [
                ft.Container(expand=True),
                PulseButton(
                    on_click_callable=_on_run_click, text="Run Now", compact=True
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
    )

    return ft.Column(content, spacing=0)


async def _trigger_job(page: ft.Page, job_id: str) -> None:
    """POST the run request and surface the result via a snackbar."""
    from app.components.frontend.state.session_state import get_session_state

    try:
        api = get_session_state(page).api_client
        result = await api.post(f"/api/v1/scheduler/jobs/{job_id}/run")
        message = (
            result.get("message", f"'{job_id}' triggered")
            if isinstance(result, dict)
            else f"Could not run '{job_id}' — it may already be running"
        )
        SuccessSnackBar(message).launch(page)
    except Exception:
        ErrorSnackBar(f"Failed to trigger '{job_id}'").launch(page)


def _build_job_row(task: dict, page: ft.Page) -> ExpandableRow:
    """Build expandable row for a scheduled job.

    Args:
        task: Task dictionary with name, next_run, schedule, status

    Returns:
        ExpandableRow with cells and expanded content
    """
    job_name = task.get("name", task.get("id", "Unknown"))
    next_run = task.get("next_run", "")
    schedule = task.get("schedule", "Unknown schedule")
    status = task.get("status", "active")

    next_run_display = format_next_run_time(next_run)
    schedule_display = format_schedule_human_readable(schedule)

    # Status dot color and text
    is_past_due = "Past due" in next_run_display
    if status != "active":
        status_color = ft.Colors.ON_SURFACE_VARIANT
        status_text = "Paused"
    elif is_past_due:
        status_color = Theme.Colors.WARNING
        status_text = "Active"
    else:
        status_color = Theme.Colors.SUCCESS
        status_text = "Active"

    cells = [
        ft.Row(
            [status_dot(status_color), TableNameText(job_name)],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        TableCellText(next_run_display),
        TableCellText(schedule_display),
        TableCellText(status_text),
    ]

    return ExpandableRow(
        cells=cells,
        expanded_content=_build_job_expanded_content(task, page),
    )


class JobsSection(ft.Container):
    """Scheduled jobs list section using ExpandableDataTable."""

    def __init__(self, metadata: dict, page: ft.Page) -> None:
        """
        Initialize jobs section.

        Args:
            metadata: Component metadata containing upcoming_tasks
            page: Flet page (passed to row actions that need it).
        """
        super().__init__()

        upcoming_tasks = metadata.get("upcoming_tasks", [])

        # Define columns
        columns = [
            DataTableColumn("Job Name"),  # expands
            DataTableColumn("Next Run", width=150),
            DataTableColumn("Schedule", width=200),
            DataTableColumn("Status", width=70),
        ]

        # Build expandable rows
        rows = [_build_job_row(task, page) for task in upcoming_tasks]

        # Build table
        self.content = ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No scheduled jobs",
        )
        self.padding = Theme.Spacing.MD


class SchedulerDetailDialog(BaseDetailPopup):
    """
    Modal dialog for displaying detailed scheduler information.

    Inherits from BaseDetailDialog for consistent modal structure.
    A tabbed layout separates the live job list from execution history.
    """

    SCHEDULER_MODAL_HEIGHT = 700

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the scheduler detail popup.

        Args:
            component_data: ComponentStatus containing scheduler health and metrics
        """
        metadata = component_data.metadata or {}

        # Jobs tab: overview metrics + the live scheduled-job list.
        jobs_tab = ft.Container(
            content=ft.Column(
                [OverviewSection(metadata), JobsSection(metadata, page)],
                spacing=0,
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
        )
        # History tab: persisted execution history (empty without persistence).
        history_tab = ft.Container(
            content=SchedulerHistorySection(page),
            expand=True,
        )

        tabs = PulseTabs(
            selected_index=0,
            expand=True,
            tabs=[
                ft.Tab(text="Jobs", content=jobs_tab),
                ft.Tab(text="History", content=history_tab),
            ],
        )

        # Initialize base popup with the tabs as a single non-scrolling section
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("scheduler"),
            subtitle_text=get_component_subtitle("scheduler", metadata),
            sections=[tabs],
            status_detail=get_status_detail(component_data),
            scrollable=False,
            height=self.SCHEDULER_MODAL_HEIGHT,
        )
