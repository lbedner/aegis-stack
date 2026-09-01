"""
Redis Card

Modern card component for displaying Redis cache status.
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


class RedisCard:
    """
    A clean Redis card with key cache metrics.

    Features:
    - Top-down layout with header and metrics
    - Hit Ratio, Memory, Ops/sec display
    - Neutral gray metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with Redis data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _get_hit_ratio_display(self) -> str:
        """Get formatted hit ratio for display."""
        hit_rate = self.metadata.get("hit_rate_percent", 0)
        return f"{hit_rate:.1f}%"

    def _get_memory_display(self) -> str:
        """Get formatted memory usage for display."""
        used_memory = self.metadata.get("used_memory", 0)
        max_memory = self.metadata.get("maxmemory", 0)

        if max_memory > 0:
            memory_percent = (used_memory / max_memory) * 100
            return f"{memory_percent:.1f}%"
        else:
            # Show absolute memory in MB
            memory_mb = used_memory / (1024 * 1024) if used_memory > 0 else 0
            if memory_mb >= 1:
                return f"{memory_mb:.1f} MB"
            else:
                memory_kb = used_memory / 1024 if used_memory > 0 else 0
                return f"{memory_kb:.0f} KB"

    def _get_ops_display(self) -> str:
        """Get formatted ops/sec for display."""
        ops_per_sec = self.metadata.get("instantaneous_ops_per_sec", 0)
        if ops_per_sec >= 1000:
            return f"{ops_per_sec / 1000:.1f}k"
        return str(int(ops_per_sec))

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        hit_ratio = self._get_hit_ratio_display()
        memory = self._get_memory_display()
        ops = self._get_ops_display()

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Hit Ratio (full width)
                    ft.Row(
                        [create_metric_container("Hit Ratio", hit_ratio)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Memory and Ops/sec
                    ft.Row(
                        [
                            create_metric_container("Memory", memory),
                            create_metric_container("Ops/sec", ops),
                        ],
                        expand=True,
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
                        "Cache",
                        "Redis",
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
        """Build and return the complete Redis card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="cache",
        )
