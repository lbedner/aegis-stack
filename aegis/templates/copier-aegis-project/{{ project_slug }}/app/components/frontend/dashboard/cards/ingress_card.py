"""
Ingress Card

Modern card component for displaying Traefik reverse proxy status.
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
from .card_metadata import metadata_number, metadata_text


class IngressCard:
    """
    A clean Ingress card with key proxy metrics.

    Features:
    - Top-down layout with header and metrics
    - Routers, Services, Entrypoints display
    - Neutral gray metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with Traefik data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _get_routers_display(self) -> str:
        """Get formatted routers count for display."""
        enabled = int(metadata_number(self.metadata, "enabled_routers"))
        total = int(metadata_number(self.metadata, "total_routers"))
        if total > 0 and enabled != total:
            return f"{enabled}/{total}"
        return str(enabled)

    def _get_services_display(self) -> str:
        """Get formatted services count for display."""
        enabled = int(metadata_number(self.metadata, "enabled_services"))
        total = int(metadata_number(self.metadata, "total_services"))
        if total > 0 and enabled != total:
            return f"{enabled}/{total}"
        return str(enabled)

    def _get_entrypoints_display(self) -> str:
        """Get formatted entrypoints for display."""
        raw = self.metadata.get("entrypoints", [])
        entrypoints = [ep for ep in raw if isinstance(ep, dict)] if isinstance(raw, list) else []
        if not entrypoints:
            return "0"
        # Show count and common ports
        ports = []
        for ep in entrypoints:
            addr = ep.get("address", "")
            if addr:
                # Extract port from address like ":80"
                port = addr.replace(":", "")
                if port:
                    ports.append(port)
        if ports:
            return f"{len(entrypoints)} ({', '.join(ports[:2])})"
        return str(len(entrypoints))

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        routers = self._get_routers_display()
        services = self._get_services_display()
        entrypoints = self._get_entrypoints_display()

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Routers (full width)
                    ft.Row(
                        [create_metric_container("Routers", routers)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Services and Entrypoints
                    ft.Row(
                        [
                            create_metric_container("Services", services),
                            create_metric_container("Ports", entrypoints),
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
        version = metadata_text(self.metadata, "version")
        subtitle = (
            f"Traefik {version}" if version and version != "unknown" else "Traefik"
        )

        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Ingress",
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
        """Build and return the complete Ingress card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="ingress",
        )
