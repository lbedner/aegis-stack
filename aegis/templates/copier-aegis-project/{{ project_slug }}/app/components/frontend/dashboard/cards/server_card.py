"""
Server Card

Modern card component for displaying server status with key system metrics.
Combines FastAPI backend and Flet frontend into a single unified view.
"""

import flet as ft

from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class ServerCard:
    """
    A clean server card with key system metrics.

    Features:
    - Real system metrics from health checks (CPU, Memory, Disk)
    - Title and health status header
    - Highlighted metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with server data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _get_cpu_display(self) -> str:
        """Get formatted CPU usage for display."""
        sub_components = self.component_data.sub_components or {}
        cpu_data = sub_components.get("cpu")
        if cpu_data and cpu_data.metadata:
            percent = cpu_data.metadata.get("percent_used", 0.0)
            return f"{percent:.1f}%"
        return "-"

    def _get_memory_display(self) -> str:
        """Get formatted memory usage for display."""
        sub_components = self.component_data.sub_components or {}
        memory_data = sub_components.get("memory")
        if memory_data and memory_data.metadata:
            percent = memory_data.metadata.get("percent_used", 0.0)
            return f"{percent:.1f}%"
        return "-"

    def _get_disk_display(self) -> str:
        """Get formatted disk usage for display."""
        sub_components = self.component_data.sub_components or {}
        disk_data = sub_components.get("disk")
        if disk_data and disk_data.metadata:
            percent = disk_data.metadata.get("percent_used", 0.0)
            return f"{percent:.1f}%"
        return "-"

    def _get_performance_summary(self) -> dict | None:
        """Performance roll-up surfaced by the request-metrics middleware.

        Returns ``None`` when no traffic has been timed yet — keeps the
        response-time row hidden on a freshly started server instead of
        showing a confusing all-zeroes block.
        """
        perf = self.metadata.get("performance") or {}
        if not isinstance(perf, dict) or not perf.get("total_requests"):
            return None
        return perf

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        cpu_display = self._get_cpu_display()
        memory_display = self._get_memory_display()
        disk_display = self._get_disk_display()
        perf = self._get_performance_summary()

        rows: list[ft.Control] = [
            # Row 1: CPU (full width)
            ft.Row(
                [create_metric_container("CPU", cpu_display)],
                expand=True,
            ),
            ft.Container(height=12),
            # Row 2: Memory and Disk
            ft.Row(
                [
                    create_metric_container("Memory", memory_display),
                    create_metric_container("Disk", disk_display),
                ],
                expand=True,
            ),
        ]

        if perf is not None:
            avg_ms = float(perf.get("avg_ms", 0.0))
            p95_ms = float(perf.get("p95_ms", 0.0))
            rows.extend(
                [
                    ft.Container(height=12),
                    # Row 3: Response-time avg + p95 (visible once
                    # the middleware has recorded at least one request).
                    ft.Row(
                        [
                            create_metric_container("Avg Response", f"{avg_ms:.0f}ms"),
                            create_metric_container("p95 Response", f"{p95_ms:.0f}ms"),
                        ],
                        expand=True,
                    ),
                ]
            )

        return ft.Container(
            content=ft.Column(rows, spacing=0),
            expand=True,
        )

    def _create_card_content(self) -> ft.Container:
        """Create the full card content with header and metrics."""
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Server",
                        "FastAPI + Flet",
                        self.component_data,
                    ),
                    self._create_metrics_section(),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build and return the complete server card."""
        # Get colors based on component status
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="backend",
        )
