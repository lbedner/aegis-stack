"""The Overview tab: what the process is doing right now.

Four metric cards over a configuration panel. ``_get_metric_color``
lives here because this is the only tab that colours a number by how
close it is to its ceiling.
"""

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ...cards.card_utils import create_progress_indicator
from ..modal_sections import (
    MetricCard,
)


def _get_metric_color(percent: float) -> str:
    """Get color based on metric percentage."""
    if percent >= 90:
        return Theme.Colors.ERROR
    elif percent >= 70:
        return Theme.Colors.WARNING
    else:
        return Theme.Colors.SUCCESS


class OverviewTab(ft.Container):
    """Overview tab combining metrics and system resources."""

    def __init__(self, backend_component: ComponentStatus) -> None:
        """
        Initialize overview tab.

        Args:
            backend_component: ComponentStatus containing backend data
        """
        super().__init__()
        metadata = backend_component.metadata or {}
        sub_components = backend_component.sub_components or {}

        # Extract metrics
        total_routes = metadata.get("total_routes", 0)
        total_endpoints = metadata.get("total_endpoints", 0)
        total_middleware = metadata.get("total_middleware", 0)
        security_count = metadata.get("security_count", 0)
        deprecated_count = metadata.get("deprecated_count", 0)
        method_counts = metadata.get("method_counts", {})

        # Build metric cards
        metric_cards = [
            MetricCard(
                value=str(total_routes),
                label="Total Routes",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=str(total_endpoints),
                label="Endpoints",
                color=Theme.Colors.SUCCESS,
            ),
            MetricCard(
                value=str(total_middleware),
                label="Middleware",
                color=ft.Colors.PURPLE,
            ),
            MetricCard(
                value=str(security_count),
                label="Security Layers",
                color=ft.Colors.AMBER,
            ),
        ]

        # Add deprecated count if any
        if deprecated_count > 0:
            metric_cards.append(
                MetricCard(
                    value=str(deprecated_count),
                    label="Deprecated",
                    color=ft.Colors.ORANGE,
                )
            )

        # Method distribution
        method_text = ", ".join(
            [f"{count} {method}" for method, count in method_counts.items()]
        )

        # Build system metrics
        cpu_data = sub_components.get("cpu")
        memory_data = sub_components.get("memory")
        disk_data = sub_components.get("disk")

        system_metrics = []

        # CPU metric
        if cpu_data and cpu_data.metadata:
            cpu_percent = cpu_data.metadata.get("percent_used", 0.0)
            cpu_cores = cpu_data.metadata.get("cpu_count", 0)
            cpu_color = _get_metric_color(cpu_percent)
            system_metrics.append(
                create_progress_indicator(
                    label=f"CPU Usage ({cpu_cores} cores)",
                    value=cpu_percent,
                    details=f"{cpu_percent:.1f}%",
                    color=cpu_color,
                )
            )

        # Memory metric
        if memory_data and memory_data.metadata:
            memory_percent = memory_data.metadata.get("percent_used", 0.0)
            memory_total = memory_data.metadata.get("total_gb", 0.0)
            memory_available = memory_data.metadata.get("available_gb", 0.0)
            memory_used = memory_total - memory_available
            memory_color = _get_metric_color(memory_percent)
            system_metrics.append(
                create_progress_indicator(
                    label="Memory Usage",
                    value=memory_percent,
                    details=f"{memory_used:.1f} / {memory_total:.1f} GB",
                    color=memory_color,
                )
            )

        # Disk metric
        if disk_data and disk_data.metadata:
            disk_percent = disk_data.metadata.get("percent_used", 0.0)
            disk_free = disk_data.metadata.get("free_gb", 0.0)
            disk_total = disk_data.metadata.get("total_gb", 0.0)
            disk_color = _get_metric_color(disk_percent)
            system_metrics.append(
                create_progress_indicator(
                    label="Disk Usage",
                    value=disk_percent,
                    details=f"{disk_free:.1f} GB free / {disk_total:.1f} GB",
                    color=disk_color,
                )
            )

        self.content = ft.Column(
            [
                # API Metrics section
                ft.Row(
                    metric_cards,
                    spacing=Theme.Spacing.MD,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            SecondaryText("HTTP Methods:"),
                            BodyText(method_text or "None"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.padding.symmetric(
                        horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
                    ),
                ),
                # System Metrics section
                ft.Container(height=Theme.Spacing.MD),  # Spacer
                H3Text("System Metrics"),
                ft.Container(
                    content=ft.Column(
                        system_metrics
                        if system_metrics
                        else [SecondaryText("No metrics available")],
                        spacing=Theme.Spacing.MD,
                    ),
                    padding=ft.padding.symmetric(vertical=Theme.Spacing.SM),
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
