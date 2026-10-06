"""
Worker Card

Modern card component for displaying arq worker queue status.
Top-down layout matching the service card pattern.
"""

import flet as ft

from app.components.frontend.controls import status_dot
from app.components.frontend.theme import AegisTheme as Theme
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_label

from .card_container import CardContainer
from .card_utils import create_header_row, get_status_colors


class WorkerCard:
    """
    A clean worker card showing queue status.

    Features:
    - Top-down layout with header and queue table
    - Queue status with counts (Queued, Active, Done, Failed)
    - Status-aware coloring
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with worker data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _get_queues_data(self) -> dict:
        """Get queue data from component."""
        if (
            self.component_data.sub_components
            and "queues" in self.component_data.sub_components
        ):
            queues_comp = self.component_data.sub_components["queues"]
            if queues_comp.sub_components:
                return queues_comp.sub_components
        return {}

    def _create_queue_table(self) -> ft.Container:
        """Create the queue status table."""
        queues_data = self._get_queues_data()

        # Table header
        header_style = ft.TextStyle(
            size=11,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

        header_row = ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=16),  # Icon column
                    ft.Container(
                        content=ft.Text("Queue", style=header_style),
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Text("Queued", style=header_style),
                        width=45,
                        alignment=ft.alignment.center_right,
                    ),
                    ft.Container(
                        content=ft.Text("Active", style=header_style),
                        width=40,
                        alignment=ft.alignment.center_right,
                    ),
                    ft.Container(
                        content=ft.Text("Done", style=header_style),
                        width=35,
                        alignment=ft.alignment.center_right,
                    ),
                    ft.Container(
                        content=ft.Text("Failed", style=header_style),
                        width=40,
                        alignment=ft.alignment.center_right,
                    ),
                    ft.Container(
                        content=ft.Text("Status", style=header_style),
                        width=50,
                        alignment=ft.alignment.center_right,
                    ),
                ],
                spacing=4,
            ),
            padding=ft.padding.only(bottom=8),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        # Build queue rows
        rows = []
        cell_style = ft.TextStyle(size=12, color=ft.Colors.ON_SURFACE)

        if queues_data:
            for queue_name, queue_data in queues_data.items():
                metadata = queue_data.metadata if queue_data else {}
                queued = metadata.get("queued_jobs", 0)
                active = metadata.get("jobs_ongoing", 0)
                completed = metadata.get("jobs_completed", 0)
                failed = metadata.get("jobs_failed", 0)
                worker_alive = metadata.get("worker_alive", False)

                # Status indicator and text
                message = queue_data.message if queue_data else ""
                if not worker_alive:
                    if "no functions" in message.lower():
                        # No tasks defined - grey
                        status_text = "N/A"
                        status_color = ft.Colors.GREY_600
                        row_opacity = 0.6
                    else:
                        # Offline - red
                        status_text = "Offline"
                        status_color = Theme.Colors.ERROR
                        row_opacity = 1.0
                elif active > 0:
                    status_text = "Active"
                    status_color = Theme.Colors.INFO
                    row_opacity = 1.0
                else:
                    status_text = "Online"
                    status_color = Theme.Colors.SUCCESS
                    row_opacity = 1.0

                row = ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=status_dot(status_color),
                                width=16,
                                alignment=ft.alignment.center,
                            ),
                            ft.Container(
                                content=ft.Text(queue_name, style=cell_style),
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Text(str(queued), style=cell_style),
                                width=45,
                                alignment=ft.alignment.center_right,
                            ),
                            ft.Container(
                                content=ft.Text(str(active), style=cell_style),
                                width=40,
                                alignment=ft.alignment.center_right,
                            ),
                            ft.Container(
                                content=ft.Text(str(completed), style=cell_style),
                                width=35,
                                alignment=ft.alignment.center_right,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    str(failed),
                                    style=ft.TextStyle(
                                        size=12,
                                        color=ft.Colors.ERROR
                                        if failed > 0
                                        else ft.Colors.ON_SURFACE,
                                    ),
                                ),
                                width=40,
                                alignment=ft.alignment.center_right,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    status_text,
                                    size=10,
                                    color=status_color,
                                    weight=ft.FontWeight.W_500,
                                ),
                                width=50,
                                alignment=ft.alignment.center_right,
                            ),
                        ],
                        spacing=4,
                    ),
                    padding=ft.padding.symmetric(vertical=6),
                    opacity=row_opacity,
                )
                rows.append(row)
        else:
            # No queues placeholder
            rows.append(
                ft.Container(
                    content=ft.Text(
                        "No queues configured",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        italic=True,
                    ),
                    padding=ft.padding.symmetric(vertical=12),
                )
            )

        return ft.Container(
            content=ft.Column(
                [header_row] + rows,
                spacing=0,
            ),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.GREY),
            border_radius=8,
            border=ft.border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.GREY)),
            padding=ft.padding.all(12),
        )

    def _create_card_content(self) -> ft.Container:
        """Create the full card content with header and queue table."""
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Worker",
                        get_component_label(ComponentName.WORKER),
                        self.component_data,
                    ),
                    self._create_queue_table(),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build and return the complete worker card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name=ComponentName.WORKER,
        )
