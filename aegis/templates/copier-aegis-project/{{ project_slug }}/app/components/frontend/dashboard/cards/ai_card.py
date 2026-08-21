"""
AI Service Card

Modern card component for displaying AI service status, provider configuration,
and conversation metrics with a clean layout.
"""

import flet as ft

from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_ai_engine_display,
    get_status_colors,
)


class AICard:
    """
    A clean AI service card with provider info and key metrics.

    Features:
    - Real AI service metrics from health checks
    - Title and health status header
    - Highlighted metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus):
        """Initialize with AI service data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _truncate_model_name(self, model: str) -> str:
        """Intelligently truncate model name for display."""
        if not model:
            return "Unknown"

        # Keep it concise but recognizable
        if len(model) <= 20:
            return model

        # Handle common patterns
        if "claude" in model.lower():
            # "claude-3-5-sonnet-20241022" -> "claude-3.5-sonnet"
            parts = model.split("-")
            if len(parts) >= 4:
                return f"{parts[0]}-{parts[1]}.{parts[2]}-{parts[3]}"
        elif "llama" in model.lower():
            # "llama-3.1-70b-versatile" -> "llama-3.1-70b"
            parts = model.split("-")
            if len(parts) >= 3:
                return "-".join(parts[:3])
        elif "gpt" in model.lower():
            # "gpt-4-turbo-preview" -> "gpt-4-turbo"
            parts = model.split("-")
            if len(parts) >= 3:
                return "-".join(parts[:3])

        # Fallback: truncate with ellipsis
        return model[:20] + "..."

    def _format_cost(self, cost: float) -> str:
        """Format cost for display."""
        if cost < 0.01:
            return f"${cost:.4f}"
        return f"${cost:.2f}"

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        # Get real data from metadata
        provider = self.metadata.get("provider", "Unknown")
        model = self.metadata.get("model", "Unknown")
        total_conversations = self.metadata.get("total_conversations", 0)
        usage_available = self.metadata.get("usage_tracking_available", False)
        total_cost = self.metadata.get("total_cost", 0.0)

        # Format values for display
        provider_display_names = {"public": "LLM7.io"}
        provider_display = provider_display_names.get(
            provider.lower(), provider.title()
        )
        model_display = self._truncate_model_name(model)
        conversations_display = str(total_conversations)
        cost_display = self._format_cost(total_cost)

        # Build second row based on whether usage tracking is available
        if usage_available:
            # Show Model and Cost when usage tracking works
            second_row = ft.Row(
                [
                    create_metric_container("Model", model_display),
                    create_metric_container("Cost", cost_display),
                ],
                expand=True,
            )
        else:
            # Show Model and Conversations when no usage tracking
            second_row = ft.Row(
                [
                    create_metric_container("Model", model_display),
                    create_metric_container("Conversations", conversations_display),
                ],
                expand=True,
            )

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Provider (full width)
                    ft.Row(
                        [create_metric_container("Provider", provider_display)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: Conditional based on usage tracking
                    second_row,
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
                        "AI Service",
                        get_ai_engine_display(self.metadata),
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
        """Build and return the complete AI service card."""
        # Get colors based on component status
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="ai",
        )
