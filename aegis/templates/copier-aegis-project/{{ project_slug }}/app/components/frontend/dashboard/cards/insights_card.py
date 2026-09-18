"""
Insights Service Card

Dashboard card for adoption metrics and analytics monitoring.
Matches the Server/Scheduler/Database card style.
"""

import flet as ft
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)
from .card_metadata import metadata_number


class InsightsCard:
    """Insights service card showing adoption metrics status."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        total_metrics = int(metadata_number(self.metadata, "total_metrics"))
        enabled_sources = int(metadata_number(self.metadata, "enabled_sources"))
        raw_stale = self.metadata.get("stale_sources", [])
        stale_sources = raw_stale if isinstance(raw_stale, list) else []
        stale_display = str(len(stale_sources)) if stale_sources else "0"

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Total Metrics (full width)
                    ft.Row(
                        [
                            create_metric_container(
                                "Total Metrics", f"{total_metrics:,}"
                            )
                        ],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Active Sources and Stale
                    ft.Row(
                        [
                            create_metric_container(
                                "Active Sources", str(enabled_sources)
                            ),
                            create_metric_container("Stale", stale_display),
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
        subtitle = get_component_subtitle("service_insights", self.metadata)

        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Insights",
                        subtitle,
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
        """Build and return the complete insights card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="service_insights",
        )
