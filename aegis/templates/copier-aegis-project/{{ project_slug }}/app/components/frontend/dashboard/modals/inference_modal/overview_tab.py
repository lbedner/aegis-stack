"""The Overview tab: what the server is doing, and what it is.

Running models and VRAM on top, server configuration under it. The
label width is shared by the two so the stat rows line up.
"""

from __future__ import annotations

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
    Tag,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import MetricCard

# Statistics section layout
STAT_LABEL_WIDTH = 200


class OverviewSection(ft.Container):
    """Overview section showing key Ollama metrics."""

    def __init__(self, ollama_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize overview section.

        Args:
            ollama_component: Ollama ComponentStatus with metadata
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ollama_component.metadata or {}

        running_models = metadata.get("running_models", [])
        running_count = metadata.get("running_models_count", 0)
        installed_count = metadata.get("installed_models_count", 0)
        total_vram_gb = metadata.get("total_vram_gb", 0.0)

        # Determine status color based on running models
        if running_count > 0:
            status_text = "Warm"
            status_color = Theme.Colors.SUCCESS
        elif installed_count > 0:
            status_text = "Cold"
            status_color = Theme.Colors.ACCENT
        else:
            status_text = "No models"
            status_color = Theme.Colors.WARNING

        # Metric cards row
        metrics_row = ft.Row(
            [
                MetricCard(
                    "VRAM Usage",
                    f"{total_vram_gb:.1f} GB",
                    Theme.Colors.SUCCESS if total_vram_gb > 0 else Theme.Colors.ACCENT,
                ),
                MetricCard(
                    "Models",
                    f"{running_count} / {installed_count}",
                    Theme.Colors.ACCENT,
                ),
                MetricCard(
                    "Status",
                    status_text,
                    status_color,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )

        # Active models display (full width, below metrics) - show all warm models
        if running_models:
            model_tags = [
                Tag(rm.get("name", "Unknown"), color=Theme.Colors.SUCCESS)
                for rm in running_models
            ]
            active_model_row = ft.Container(
                content=ft.Row(
                    [
                        SecondaryText("Active Models:", width=110),
                        ft.Row(model_tags, spacing=Theme.Spacing.XS, wrap=True),
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(top=Theme.Spacing.MD),
            )
        else:
            active_model_row = ft.Container(
                content=ft.Row(
                    [
                        SecondaryText("Active Models:", width=110),
                        SecondaryText("None loaded", italic=True),
                    ],
                    spacing=Theme.Spacing.SM,
                ),
                padding=ft.padding.only(top=Theme.Spacing.MD),
            )

        self.content = ft.Column(
            [metrics_row, active_model_row],
            spacing=0,
        )


class ServerInfoSection(ft.Container):
    """Server information section showing connection details."""

    def __init__(self, ollama_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize server info section.

        Args:
            ollama_component: Ollama ComponentStatus with metadata
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ollama_component.metadata or {}
        response_time = ollama_component.response_time_ms or 0

        base_url = metadata.get("base_url", "http://localhost:11434")
        version = metadata.get("version", "Unknown")
        available = metadata.get("available", False)

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
                H3Text("Server Information"),
                ft.Container(height=Theme.Spacing.SM),
                info_row("Base URL", base_url),
                info_row("Version", version if version else "Unknown"),
                info_row("Status", "Available" if available else "Unavailable"),
                info_row("Response Time", f"{response_time:.0f}ms"),
            ],
            spacing=Theme.Spacing.XS,
        )


class OverviewTab(ft.Container):
    """Overview tab combining metrics and server info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.content = ft.Column(
            [
                OverviewSection(component_data, page),
                ServerInfoSection(component_data, page),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True
