"""The hero numbers, and the two pie cards beside them."""

from typing import Any

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme
from app.components.frontend.theme import DarkColorPalette
from app.core.formatting import format_cost, format_number

from ..modal_sections import MetricCard, PieChartCard


def _get_success_rate_color(rate: float) -> str:
    """Get color based on success rate percentage."""
    if rate >= 95:
        return Theme.Colors.SUCCESS
    elif rate >= 80:
        return ft.Colors.ORANGE
    else:
        return Theme.Colors.ERROR


class HeroStatsSection(ft.Container):
    """Hero stats section showing key metrics in cards."""

    def __init__(self, stats: dict[str, Any]) -> None:
        """
        Initialize hero stats section.

        Args:
            stats: Dictionary with usage statistics
        """
        super().__init__()

        total_tokens = stats.get("total_tokens", 0)
        total_cost = stats.get("total_cost", 0.0)
        success_rate = stats.get("success_rate", 0.0)
        total_requests = stats.get("total_requests", 0)

        self.content = ft.Column(
            [
                ft.Row(
                    [
                        MetricCard(
                            "Total Tokens",
                            format_number(total_tokens),
                            ft.Colors.PURPLE,
                        ),
                        MetricCard(
                            "Total Cost",
                            format_cost(total_cost),
                            Theme.Colors.PRIMARY,
                        ),
                        MetricCard(
                            "Success Rate",
                            f"{success_rate:.1f}%",
                            _get_success_rate_color(success_rate),
                        ),
                        MetricCard(
                            "Requests",
                            format_number(total_requests),
                            ft.Colors.CYAN,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                ),
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


def _create_token_breakdown_card(stats: dict[str, Any]) -> PieChartCard:
    """Create token breakdown pie chart card."""
    input_tokens = stats.get("input_tokens", 0)
    output_tokens = stats.get("output_tokens", 0)
    total = input_tokens + output_tokens

    if total == 0:
        return PieChartCard("Token Breakdown", [])

    input_pct = input_tokens / total * 100
    output_pct = output_tokens / total * 100

    return PieChartCard(
        title="Token Breakdown",
        sections=[
            {
                "value": input_tokens,
                "color": DarkColorPalette.ACCENT,
                "label": f"Input Tokens ({input_pct:.1f}%)",
            },
            {
                "value": output_tokens,
                "color": ft.Colors.PURPLE_200,
                "label": f"Output Tokens ({output_pct:.1f}%)",
            },
        ],
    )


def _create_model_usage_card(stats: dict[str, Any]) -> PieChartCard:
    """Create model usage pie chart card."""
    models = stats.get("models", [])

    if not models:
        return PieChartCard("Model Usage", [])

    sections = []
    for model in models:
        pct = float(model.get("pct", 0))
        name = model.get("name", "Unknown")

        # Don't pass color - let PieChartCard auto-assign from palette
        sections.append(
            {
                "value": pct,
                "label": f"{name} ({pct:.1f}%)",
            }
        )

    return PieChartCard(title="Model Usage", sections=sections)
