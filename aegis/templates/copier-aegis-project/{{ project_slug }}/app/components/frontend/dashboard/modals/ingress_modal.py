"""
Ingress Detail Modal

Displays comprehensive Traefik reverse proxy information including
routers, services, and entrypoints configuration.
"""

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

# Table column widths
COL_WIDTH_ROUTER_NAME = 180
COL_WIDTH_RULE = 280
COL_WIDTH_SERVICE = 150
COL_WIDTH_ENTRYPOINTS = 120
COL_WIDTH_TLS = 60

COL_WIDTH_EP_NAME = 150
COL_WIDTH_EP_ADDRESS = 200

# Statistics section layout
STAT_LABEL_WIDTH = 150


class OverviewSection(ft.Container):
    """Overview section showing key Traefik metrics."""

    def __init__(self, ingress_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize overview section.

        Args:
            ingress_component: Ingress ComponentStatus with metadata
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ingress_component.metadata or {}

        enabled_routers = metadata.get("enabled_routers", 0)
        total_routers = metadata.get("total_routers", 0)
        enabled_services = metadata.get("enabled_services", 0)
        total_services = metadata.get("total_services", 0)
        entrypoints = metadata.get("entrypoints", [])
        version = metadata.get("version", "unknown")

        # Determine router health color
        if enabled_routers > 0:
            router_color = Theme.Colors.SUCCESS
        else:
            router_color = Theme.Colors.WARNING

        # Determine service health color
        if enabled_services > 0:
            service_color = Theme.Colors.SUCCESS
        else:
            service_color = Theme.Colors.WARNING

        self.content = ft.Row(
            [
                MetricCard(
                    "Version",
                    version,
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Routers",
                    f"{enabled_routers}/{total_routers}",
                    router_color,
                ),
                MetricCard(
                    "Services",
                    f"{enabled_services}/{total_services}",
                    service_color,
                ),
                MetricCard(
                    "Entrypoints",
                    str(len(entrypoints)),
                    Theme.Colors.INFO,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )


class ConnectionSection(ft.Container):
    """Connection info section showing API URL and status."""

    def __init__(self, ingress_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize connection section.

        Args:
            ingress_component: Ingress ComponentStatus with metadata
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ingress_component.metadata or {}

        api_url = metadata.get("api_url", "Not configured")
        available = metadata.get("available", False)
        codename = metadata.get("codename", "")

        def info_row(label: str, value: str) -> ft.Row:
            """Create an info row."""
            return ft.Row(
                [
                    SecondaryText(
                        f"{label}:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=STAT_LABEL_WIDTH,
                    ),
                    BodyText(value),
                ],
                spacing=Theme.Spacing.MD,
            )

        self.content = ft.Column(
            [
                H3Text("Connection Info"),
                ft.Container(height=Theme.Spacing.SM),
                info_row("API URL", api_url),
                info_row("Status", "Available" if available else "Unavailable"),
                info_row("Codename", codename if codename else "N/A"),
            ],
            spacing=Theme.Spacing.XS,
        )


class RouterRow(ft.Container):
    """Single router display row."""

    def __init__(self, router: dict) -> None:
        """
        Initialize router row.

        Args:
            router: Router info dict with name, rule, service, entryPoints, tls
        """
        super().__init__()

        name = router.get("name", "unknown")
        rule = router.get("rule", "")
        service = router.get("service", "")
        entry_points = router.get("entryPoints", [])
        has_tls = router.get("tls", False)

        # Format entrypoints as comma-separated list
        ep_str = ", ".join(entry_points) if entry_points else "none"

        # TLS indicator
        tls_color = Theme.Colors.SUCCESS if has_tls else ft.Colors.ON_SURFACE_VARIANT
        tls_text = "Yes" if has_tls else "No"

        self.content = ft.Row(
            [
                ft.Container(
                    content=BodyText(name),
                    width=COL_WIDTH_ROUTER_NAME,
                ),
                ft.Container(
                    content=BodyText(
                        rule[:40] + "..." if len(rule) > 40 else rule,
                        tooltip=rule if len(rule) > 40 else None,
                    ),
                    width=COL_WIDTH_RULE,
                ),
                ft.Container(
                    content=BodyText(service),
                    width=COL_WIDTH_SERVICE,
                ),
                ft.Container(
                    content=BodyText(ep_str),
                    width=COL_WIDTH_ENTRYPOINTS,
                ),
                ft.Container(
                    content=SecondaryText(
                        tls_text,
                        color=tls_color,
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    ),
                    width=COL_WIDTH_TLS,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.XS)


class RoutersSection(ft.Container):
    """Routers section displaying active HTTP routers."""

    def __init__(self, ingress_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize routers section.

        Args:
            ingress_component: Ingress ComponentStatus with routers list
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ingress_component.metadata or {}
        routers = metadata.get("routers", [])

        # Column headers
        header_row = ft.Row(
            [
                ft.Container(
                    content=SecondaryText(
                        "Name", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_ROUTER_NAME,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Rule", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_RULE,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Service", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_SERVICE,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Entry Points", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_ENTRYPOINTS,
                ),
                ft.Container(
                    content=SecondaryText(
                        "TLS", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_TLS,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Router rows
        router_rows = [RouterRow(router) for router in routers]

        if router_rows:
            self.content = ft.Column(
                [
                    header_row,
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Column(router_rows, spacing=0),
                ],
                spacing=0,
            )
        else:
            self.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(
                            ft.Icons.ROUTE,
                            size=48,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        SecondaryText("No routers configured"),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.SM,
                ),
                alignment=ft.alignment.center,
                expand=True,
            )
            self.expand = True


class EntrypointRow(ft.Container):
    """Single entrypoint display row."""

    def __init__(self, entrypoint: dict) -> None:
        """
        Initialize entrypoint row.

        Args:
            entrypoint: Entrypoint info dict with name and address
        """
        super().__init__()

        name = entrypoint.get("name", "unknown")
        address = entrypoint.get("address", "unknown")

        self.content = ft.Row(
            [
                ft.Container(
                    content=BodyText(name),
                    width=COL_WIDTH_EP_NAME,
                ),
                ft.Container(
                    content=BodyText(address),
                    width=COL_WIDTH_EP_ADDRESS,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.XS)


class EntrypointsSection(ft.Container):
    """Entrypoints section displaying Traefik entrypoints."""

    def __init__(self, ingress_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize entrypoints section.

        Args:
            ingress_component: Ingress ComponentStatus with entrypoints list
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ingress_component.metadata or {}
        entrypoints = metadata.get("entrypoints", [])

        # Column headers
        header_row = ft.Row(
            [
                ft.Container(
                    content=SecondaryText(
                        "Name", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_EP_NAME,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Address", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_EP_ADDRESS,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Entrypoint rows
        ep_rows = [EntrypointRow(ep) for ep in entrypoints]

        if ep_rows:
            self.content = ft.Column(
                [
                    H3Text("Entrypoints"),
                    ft.Container(height=Theme.Spacing.SM),
                    header_row,
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Column(ep_rows, spacing=0),
                ],
                spacing=0,
            )
        else:
            self.content = ft.Column(
                [
                    H3Text("Entrypoints"),
                    ft.Container(height=Theme.Spacing.SM),
                    ft.Container(
                        content=SecondaryText("No entrypoints configured"),
                        alignment=ft.alignment.center,
                    ),
                ],
                spacing=0,
            )


# =============================================================================
# Tab Containers
# =============================================================================


class OverviewTab(ft.Container):
    """Overview tab combining metrics and connection info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.content = ft.Column(
            [
                OverviewSection(component_data, page),
                ConnectionSection(component_data, page),
                EntrypointsSection(component_data, page),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


class RoutersTab(ft.Container):
    """Routers tab showing HTTP router configuration."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = component_data.metadata or {}
        routers = metadata.get("routers", [])

        if routers:
            self.content = ft.Column(
                [RoutersSection(component_data, page)],
                scroll=ft.ScrollMode.AUTO,
            )
            self.padding = ft.padding.all(Theme.Spacing.SM)
        else:
            self.content = ft.Column(
                [
                    ft.Icon(
                        ft.Icons.ROUTE,
                        size=48,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    SecondaryText("No routers configured"),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
                expand=True,
            )
        self.expand = True


# =============================================================================
# Main Dialog
# =============================================================================


class IngressDetailDialog(BaseDetailPopup):
    """
    Traefik ingress detail popup dialog.

    Displays comprehensive Traefik information including routers,
    services, and entrypoints configuration.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the ingress details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
            page: Flet page instance
        """
        metadata = component_data.metadata or {}
        version = metadata.get("version", "")
        subtitle = f"Traefik {version}" if version else "Traefik"

        # Build tabs
        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=OverviewTab(component_data, page)),
                ft.Tab(text="Routers", content=RoutersTab(component_data, page)),
            ],
            expand=True,
        )

        # Initialize base popup with tabs
        super().__init__(
            page=page,
            component_data=component_data,
            title_text="Ingress",
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=900,
            height=600,
            status_detail=get_status_detail(component_data),
        )
