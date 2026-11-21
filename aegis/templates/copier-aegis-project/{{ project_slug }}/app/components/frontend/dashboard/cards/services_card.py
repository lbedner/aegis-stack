"""
Services Component Card

Modern card component that displays service health status, including authentication,
payment, AI, and other business logic services. Shows overview statistics and
individual service statuses.
"""

import flet as ft

from app.components.frontend.controls import LabelText, PrimaryText
from app.components.frontend.controls.tech_badge import TechBadge
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_responsive_3_section_layout,
    create_stats_row,
    get_status_colors,
)


class ServicesCard:
    """
    A visually stunning component card for displaying services health and status.

    Features:
    - Overview of all registered services
    - Individual service health indicators
    - Service dependency status
    - Modern Material Design 3 styling
    """

    def __init__(self, component_data: ComponentStatus):
        """Initialize with component data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_service_indicators(self) -> ft.Column:
        """Create visual indicators for individual services."""
        service_items = []

        # Get individual services from sub_components
        services = self.component_data.sub_components or {}

        if not services:
            return ft.Container(
                content=LabelText("No services registered"),
                padding=ft.padding.all(12),
                bgcolor=Theme.Colors.SURFACE_2,
                border_radius=8,
            )

        for service_name, service_status in services.items():
            # Get service type from metadata if available
            service_type = service_status.metadata.get("service_type", service_name)

            # Create status indicator
            status_color = get_status_colors(service_status)[0]

            service_item = ft.Container(
                content=ft.Row(
                    [
                        # Service status indicator
                        ft.Container(
                            width=8,
                            height=8,
                            bgcolor=status_color,
                            border_radius=4,
                        ),
                        # Service name and type
                        ft.Column(
                            [
                                PrimaryText(service_name.title()),
                                LabelText(service_type, size=12),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        # Service status text
                        LabelText(
                            service_status.status.value.title(),
                            size=12,
                            color=status_color,
                            weight=ft.FontWeight.W_500,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                padding=ft.padding.symmetric(vertical=8, horizontal=12),
                bgcolor=ft.Colors.with_opacity(0.03, status_color),
                border_radius=8,
                border=ft.border.all(1, ft.Colors.with_opacity(0.1, status_color)),
            )
            service_items.append(service_item)

        return ft.Column(service_items, spacing=8)

    def _create_services_overview(self) -> ft.Container:
        """Create the services overview section."""
        total_services = self.metadata.get("total_services", 0)

        # Create overview stats
        active_count = len(
            [s for s in self.component_data.sub_components.values() if s.healthy]
        )
        types_count = len(
            {
                s.metadata.get("service_type", "unknown")
                for s in self.component_data.sub_components.values()
            }
        )

        stats_rows = [
            create_stats_row("Total", str(total_services)),
            create_stats_row("Active", str(active_count)),
            create_stats_row("Types", str(types_count)),
        ]

        return ft.Container(
            content=ft.Column(
                [
                    PrimaryText("Services Overview"),
                    ft.Container(height=8),  # Spacing
                    ft.Column(stats_rows, spacing=4),
                    ft.Container(height=12),  # Spacing
                    self._create_service_indicators(),
                ]
            ),
            expand=True,
        )

    def _create_technology_badge(self) -> ft.Container:
        """Create technology badge for services."""
        primary_color, _, _ = get_status_colors(self.component_data)

        return TechBadge(
            title="Business Logic",
            subtitle="Application Services",
            primary_color=primary_color,
        )

    def _create_stats_section(self) -> ft.Container:
        """Create the right stats section."""
        response_time = self.component_data.response_time_ms

        stats_items = []

        # Response time
        if response_time is not None:
            stats_items.append(
                ft.Container(
                    content=ft.Column(
                        [
                            LabelText("Response Time", size=12),
                            PrimaryText(f"{response_time:.1f}ms"),
                        ],
                        spacing=4,
                    ),
                    padding=ft.padding.all(12),
                    bgcolor=ft.Colors.with_opacity(0.05, Theme.Colors.INFO),
                    border_radius=8,
                )
            )

        # Service dependencies
        dependencies_healthy = True
        for service in self.component_data.sub_components.values():
            service_deps = service.metadata.get("dependencies", {})
            for _dep_name, dep_status in service_deps.items():
                if dep_status != "available":
                    dependencies_healthy = False
                    break

        dep_color = (
            Theme.Colors.SUCCESS if dependencies_healthy else Theme.Colors.WARNING
        )
        stats_items.append(
            ft.Container(
                content=ft.Column(
                    [
                        LabelText("Dependencies", size=12),
                        ft.Text(
                            "Healthy" if dependencies_healthy else "Issues",
                            color=dep_color,
                            size=16,
                            weight=ft.FontWeight.W_400,
                        ),
                    ],
                    spacing=4,
                ),
                padding=ft.padding.all(12),
                bgcolor=ft.Colors.with_opacity(0.05, dep_color),
                border_radius=8,
            )
        )

        return ft.Container(
            content=ft.Column(stats_items, spacing=8),
            width=140,
        )

    def build(self) -> ft.Container:
        """Build and return the complete services card."""
        # Get colors based on component status
        background_color, primary_color, border_color = get_status_colors(
            self.component_data
        )

        # Use shared responsive 3-section layout
        content = create_responsive_3_section_layout(
            left_content=self._create_technology_badge(),
            middle_content=self._create_services_overview(),
            right_content=self._create_stats_section(),
        )

        return CardContainer(
            content=content,
            border_color=border_color,
            component_data=self.component_data,
            component_name="services",
        )
