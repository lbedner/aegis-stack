"""
Database Component Card

Modern card component for displaying database status with key metrics.
Supports both SQLite and PostgreSQL backends.
"""

import flet as ft

from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class DatabaseCard:
    """
    A clean database card with key metrics.

    Features:
    - Real database metrics from health checks
    - Title and health status header
    - Highlighted metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with database data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _get_version_display(self) -> str:
        """Get formatted version string for display."""
        implementation = self.metadata.get("implementation", "sqlite")

        if implementation == "postgresql":
            # Try version_short first, then extract from full version
            if "version_short" in self.metadata:
                return f"PostgreSQL {self.metadata['version_short']}"
            elif "version" in self.metadata:
                version = self.metadata["version"]
                if isinstance(version, str) and "PostgreSQL" in version:
                    parts = version.split()
                    if len(parts) >= 2:
                        return f"PostgreSQL {parts[1]}"
            return "PostgreSQL"
        else:
            # SQLite
            if "version" in self.metadata:
                return f"SQLite {self.metadata['version']}"
            return "SQLite"

    def _get_size_display(self) -> str:
        """Get formatted database size for display."""
        implementation = self.metadata.get("implementation", "sqlite")

        if implementation == "postgresql":
            if "database_size_human" in self.metadata:
                return self.metadata["database_size_human"]
        else:
            # SQLite
            if "file_size_human" in self.metadata:
                return self.metadata["file_size_human"]
            elif "file_size_bytes" in self.metadata:
                size_bytes = self.metadata["file_size_bytes"]
                if size_bytes == 0:
                    return "0 B"
                elif size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024**2:
                    return f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024**3:
                    return f"{size_bytes / (1024**2):.1f} MB"
                else:
                    return f"{size_bytes / (1024**3):.1f} GB"

        return "-"

    def _get_connections_display(self) -> str:
        """Get formatted connections string for display."""
        implementation = self.metadata.get("implementation", "sqlite")

        if implementation == "postgresql":
            active = self.metadata.get("active_connections", 0)
            # Try to get max connections from pg_settings
            pg_settings = self.metadata.get("pg_settings", {})
            max_conn = pg_settings.get("max_connections", 100)
            return f"{active} / {max_conn}"
        else:
            # SQLite - show pool size as "connections"
            pool_size = self.metadata.get("connection_pool_size", 1)
            return str(pool_size)

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        # Get real data from metadata
        size_display = self._get_size_display()
        connections_display = self._get_connections_display()
        table_count = self.metadata.get("table_count", 0)

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Size (full width)
                    ft.Row(
                        [create_metric_container("Size", size_display)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Connections and Tables
                    ft.Row(
                        [
                            create_metric_container("Connections", connections_display),
                            create_metric_container("Tables", str(table_count)),
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
                        "Database",
                        self._get_version_display(),
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
        """Build and return the complete database card."""
        # Get colors based on component status
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="database",
        )
