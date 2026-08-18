"""
Observability Card

Modern card component for displaying Logfire observability status
with trace analytics when the Query API is available.
Top-down layout matching the service card pattern.
"""

import flet as ft

from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class ObservabilityCard:
    """
    A clean Observability card with Logfire status and trace analytics.

    Features:
    - Trace count and exception count when Query API is available
    - Average and max latency display
    - Fallback to cloud status + hint when no read token
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with observability data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _has_query_api(self) -> bool:
        """Check if Logfire Query API data is available."""
        return bool(self.metadata.get("query_api_available"))

    def _get_cloud_status(self) -> str:
        """Get Logfire cloud connection status."""
        if self.metadata.get("send_to_logfire"):
            return "Active"
        return "Local only"

    def _format_latency(self, ms: float) -> str:
        """Format latency value for display."""
        if ms == 0:
            return "0 ms"
        if ms < 1:
            return f"{ms:.2f} ms"
        if ms < 1000:
            return f"{ms:.0f} ms"
        return f"{ms / 1000:.1f} s"

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with trace analytics or fallback."""
        if self._has_query_api():
            return self._create_analytics_metrics()
        return self._create_fallback_metrics()

    def _create_analytics_metrics(self) -> ft.Container:
        """Create metrics section with trace analytics data."""
        total_traces = self.metadata.get("total_traces", 0)
        exceptions = self.metadata.get("exceptions", 0)
        avg_ms = self.metadata.get("avg_duration_ms", 0)
        max_ms = self.metadata.get("max_duration_ms", 0)

        # Format exception display with visual emphasis
        exc_str = str(exceptions)

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Traces and Exceptions
                    ft.Row(
                        [
                            create_metric_container("Traces (1h)", str(total_traces)),
                            create_metric_container("Exceptions", exc_str),
                        ],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Avg Latency and Max Latency
                    ft.Row(
                        [
                            create_metric_container(
                                "Avg Latency", self._format_latency(avg_ms)
                            ),
                            create_metric_container(
                                "Max Latency", self._format_latency(max_ms)
                            ),
                        ],
                        expand=True,
                    ),
                ],
                spacing=0,
            ),
            expand=True,
        )

    def _create_fallback_metrics(self) -> ft.Container:
        """Create fallback metrics when no read token is configured."""
        cloud_status = self._get_cloud_status()

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Cloud status
                    ft.Row(
                        [create_metric_container("Cloud", cloud_status)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Hint to add read token
                    ft.Container(
                        content=ft.Text(
                            "Add LOGFIRE_READ_TOKEN for trace analytics",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            italic=True,
                        ),
                        padding=ft.padding.symmetric(horizontal=16),
                    ),
                ],
                spacing=0,
            ),
            expand=True,
        )

    def _create_card_content(self) -> ft.Container:
        """Create the full card content with header and metrics."""
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Observability",
                        f"Pydantic Logfire {self.metadata.get('logfire_version', '')}".strip(),
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
        """Build and return the complete Observability card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="observability",
        )
