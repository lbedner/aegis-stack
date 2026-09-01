"""
Authentication Service Card

Modern card component specifically designed for authentication service monitoring.
Shows auth-specific metrics with a clean, functional layout.
"""

import flet as ft
from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class AuthCard:
    """
    A clean authentication service card with real metrics.

    Features:
    - Real authentication metrics from health checks
    - Title and health status header
    - Highlighted metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus):
        """Initialize with authentication service data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        # Get real data from metadata
        user_count_display = self.metadata.get("user_count_display", "0")
        jwt_algorithm = self.metadata.get("jwt_algorithm", "HS256")
        token_expiry_display = self.metadata.get("token_expiry_display", "30 min")

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Total Users (full width)
                    ft.Row(
                        [create_metric_container("Total Users", user_count_display)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Algorithm and Token Expiry
                    ft.Row(
                        [
                            create_metric_container("Algorithm", jwt_algorithm),
                            create_metric_container(
                                "Token Expiry", token_expiry_display
                            ),
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
                        "Auth Service",
                        "JWT Authentication",
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
        """Build and return the complete authentication card."""
        # Get colors based on component status
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="service_auth",
        )
