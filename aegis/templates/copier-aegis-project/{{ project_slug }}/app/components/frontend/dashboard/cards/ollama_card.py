"""
Ollama Card

Modern card component for displaying Ollama local LLM infrastructure status.
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


class OllamaCard:
    """
    A clean Ollama card with key infrastructure metrics.

    Features:
    - Top-down layout with header and metrics
    - Running model, VRAM usage, models count display
    - Neutral gray metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus) -> None:
        """Initialize with Ollama data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _get_model_display(self) -> str:
        """Get the primary running model name for display."""
        running_models = self.metadata.get("running_models", [])
        if running_models:
            model_name = running_models[0].get("name", "Unknown")
            # Truncate long model names
            if len(model_name) > 18:
                return model_name[:15] + "..."
            return model_name
        return "None loaded"

    def _get_vram_display(self) -> str:
        """Get formatted VRAM usage for display."""
        total_vram_gb = self.metadata.get("total_vram_gb", 0)
        if total_vram_gb > 0:
            return f"{total_vram_gb:.1f} GB"
        return "0 GB"

    def _get_models_count_display(self) -> str:
        """Get models count for display."""
        running = self.metadata.get("running_models_count", 0)
        installed = self.metadata.get("installed_models_count", 0)
        if running > 0:
            return f"{running} warm / {installed}"
        return f"0 / {installed}"

    def _get_status_display(self) -> str:
        """Get status indicator for display."""
        if not self.metadata.get("available", False):
            return "Offline"
        running_models = self.metadata.get("running_models", [])
        if running_models:
            return "Warm"
        return "Cold"

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        model = self._get_model_display()
        vram = self._get_vram_display()
        models_count = self._get_models_count_display()

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Active Model (full width)
                    ft.Row(
                        [create_metric_container("Active Model", model)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: VRAM and Models
                    ft.Row(
                        [
                            create_metric_container("VRAM", vram),
                            create_metric_container("Models", models_count),
                        ],
                        expand=True,
                    ),
                ],
                spacing=0,
            ),
            expand=True,
        )

    def _get_subtitle(self) -> str:
        """Get subtitle showing Ollama with version."""
        version = self.metadata.get("version", "")
        if version:
            return f"Ollama v{version}"
        return "Ollama"

    def _create_card_content(self) -> ft.Container:
        """Create the full card content with header and metrics."""
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Inference",
                        self._get_subtitle(),
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
        """Build and return the complete Ollama card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="ollama",
        )
