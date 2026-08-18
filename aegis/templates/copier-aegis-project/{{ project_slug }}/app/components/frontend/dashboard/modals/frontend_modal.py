"""
Frontend Detail Modal

Displays comprehensive frontend framework information including Flet capabilities,
configuration, and integration status.
"""

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    H3Text,
    LabelText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard


class OverviewSection(ft.Container):
    """Overview section showing key frontend metrics."""

    def __init__(self, metadata: dict) -> None:
        """
        Initialize overview section.

        Args:
            metadata: Component metadata containing frontend information
        """
        super().__init__()

        framework = metadata.get("framework", "Flet")
        version = metadata.get("version", "Unknown")
        integration = metadata.get("integration", "FastAPI")
        theme_support = metadata.get("theme_support", "Light / Dark")

        self.content = ft.Row(
            [
                MetricCard(
                    "Framework",
                    f"{framework} {version}",
                    Theme.Colors.PRIMARY,
                ),
                MetricCard(
                    "Integration",
                    integration,
                    Theme.Colors.SUCCESS,
                ),
                MetricCard(
                    "Theme",
                    theme_support,
                    Theme.Colors.INFO,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


class ConfigurationSection(ft.Container):
    """Configuration section showing framework settings and details."""

    def __init__(self, metadata: dict) -> None:
        """
        Initialize configuration section.

        Args:
            metadata: Component metadata containing configuration
        """
        super().__init__()

        framework = metadata.get("framework", "Flet")
        version = metadata.get("version", "Unknown")
        integration = metadata.get("integration", "FastAPI")
        ui_type = metadata.get("ui_type", "Reactive Web")
        platform = metadata.get("platform", "Cross-platform")
        components = metadata.get("components", "Material 3")
        theme_support = metadata.get("theme_support", "Light / Dark")
        auto_refresh = metadata.get("auto_refresh", 30)

        # Build configuration rows
        config_rows = []

        # Framework row with badge
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "Framework:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    ft.Container(
                        content=LabelText(
                            f"{framework} {version}", color=Theme.Colors.BADGE_TEXT
                        ),
                        padding=ft.padding.symmetric(
                            horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.XS
                        ),
                        bgcolor=Theme.Colors.PRIMARY,
                        border_radius=Theme.Components.BADGE_RADIUS,
                    ),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Integration Type row
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "Integration Type:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(f"{integration} integrated"),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # UI Type row
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "UI Type:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(ui_type),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Platform row
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "Platform:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(platform),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Components row
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "Components:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(components),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Theme Support row
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "Theme Support:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(f"{theme_support} available"),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        # Auto Refresh row
        config_rows.append(
            ft.Row(
                [
                    SecondaryText(
                        "Auto Refresh:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(f"Every {auto_refresh} seconds"),
                ],
                spacing=Theme.Spacing.MD,
            )
        )

        self.content = ft.Column(
            [
                H3Text("Configuration"),
                ft.Container(height=Theme.Spacing.SM),
                ft.Column(config_rows, spacing=Theme.Spacing.SM),
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


class CapabilitiesSection(ft.Container):
    """Capabilities section showing frontend features and capabilities."""

    def __init__(self, metadata: dict) -> None:
        """
        Initialize capabilities section.

        Args:
            metadata: Component metadata containing capability information
        """
        super().__init__()

        # Build capability rows
        capability_rows = []

        # Material Design 3
        capability_rows.append(BodyText("• Material Design 3"))

        # Theme Switching
        capability_rows.append(BodyText("• Theme Switching (Light/Dark)"))

        # Auto Refresh
        auto_refresh = metadata.get("auto_refresh", 30)
        capability_rows.append(BodyText(f"• Auto Refresh ({auto_refresh}s)"))

        # Reactive UI Updates
        capability_rows.append(BodyText("• Reactive UI Updates"))

        # Cross-platform Rendering
        capability_rows.append(BodyText("• Cross-platform Rendering"))

        # FastAPI Integration
        integration = metadata.get("integration", "FastAPI")
        capability_rows.append(BodyText(f"• {integration} Integration"))

        self.content = ft.Column(
            [
                H3Text("Capabilities"),
                ft.Container(height=Theme.Spacing.SM),
                ft.Column(capability_rows, spacing=Theme.Spacing.SM),
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


class StatisticsSection(ft.Container):
    """Statistics section showing detailed metrics and technical information."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize statistics section.

        Args:
            component_data: Complete component status information
        """
        super().__init__()

        status = component_data.status
        message = component_data.message
        response_time = component_data.response_time_ms or 0
        metadata = component_data.metadata or {}

        # Dependencies
        dependencies = metadata.get("dependencies", {})
        backend_dep = dependencies.get("backend", "Available")

        def stat_row(label: str, value: str) -> ft.Row:
            """Create a statistics row with label and value."""
            return ft.Row(
                [
                    SecondaryText(
                        f"{label}:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=200,
                    ),
                    BodyText(value),
                ],
                spacing=Theme.Spacing.MD,
            )

        self.content = ft.Column(
            [
                H3Text("Statistics"),
                ft.Container(height=Theme.Spacing.SM),
                stat_row("Component Status", status.value.upper()),
                stat_row("Health Message", message),
                stat_row("Response Time", f"{response_time:.2f}ms"),
                ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                stat_row("Backend Integration", backend_dep),
            ],
            spacing=Theme.Spacing.XS,
        )
        self.padding = Theme.Spacing.MD


class FrontendDetailDialog(BaseDetailPopup):
    """
    Frontend detail popup dialog.

    Displays comprehensive frontend framework information including Flet capabilities,
    configuration, and integration status.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the frontend details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
        """
        metadata = component_data.metadata or {}

        # Build sections
        sections = [
            OverviewSection(metadata),
            ConfigurationSection(metadata),
            ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
            CapabilitiesSection(metadata),
            ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
            StatisticsSection(component_data, page),
        ]

        # Initialize base popup with custom sections
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("frontend"),
            subtitle_text=get_component_subtitle("frontend", metadata),
            sections=sections,
            status_detail=get_status_detail(component_data),
        )
