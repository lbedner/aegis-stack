"""The featured shelf: what to try first."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import EmptyStatePlaceholder, SectionHeader
from .formatting import (
    _extract_model_date,
    _format_context,
    _format_price,
    _is_alias_model,
)

# Featured vendors (2 per row)
# Note: These must match vendor names from OpenRouter exactly
FEATURED_VENDORS = ["openai", "anthropic", "google", "xai", "deepseek", "groq"]


MODELS_PER_VENDOR = 5


# Vendor display names and colors
VENDOR_DISPLAY = {
    "openai": {"name": "OpenAI", "color": "#10A37F"},
    "anthropic": {"name": "Anthropic", "color": "#D4A574"},
    "google": {"name": "Google", "color": "#4285F4"},
    "xai": {"name": "Grok", "color": "#1DA1F2"},
    "deepseek": {"name": "DeepSeek", "color": "#5B6EE1"},
    "groq": {"name": "Groq", "color": "#F55036"},
}


class FeaturedModelsSection(ft.Container):
    """Featured models from Big 3 vendors (OpenAI, Anthropic, Google)."""

    def __init__(self, featured_models: dict[str, list[dict[str, Any]]]) -> None:
        """
        Initialize featured models section.

        Args:
            featured_models: Dict mapping vendor name to list of model dicts
        """
        super().__init__()

        if not any(featured_models.values()):
            self.content = ft.Column(
                [
                    SectionHeader("Featured Models"),
                    ft.Container(height=Theme.Spacing.SM),
                    EmptyStatePlaceholder(
                        "No models found. Run 'llm sync' to populate."
                    ),
                ],
                spacing=0,
            )
        else:
            vendor_sections = []

            for vendor_key in FEATURED_VENDORS:
                models = featured_models.get(vendor_key, [])
                if not models:
                    continue

                # Filter out aliases and sort by date (newest first)
                filtered = [
                    m for m in models if not _is_alias_model(m.get("model_id", ""))
                ]
                sorted_models = sorted(
                    filtered,
                    key=_extract_model_date,
                    reverse=True,
                )[:MODELS_PER_VENDOR]

                if not sorted_models:
                    continue

                vendor_info = VENDOR_DISPLAY.get(
                    vendor_key,
                    {"name": vendor_key.title(), "color": Theme.Colors.PRIMARY},
                )

                # Vendor header with column labels
                vendor_header = ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                width=4,
                                height=20,
                                bgcolor=vendor_info["color"],
                                border_radius=2,
                            ),
                            ft.Text(
                                vendor_info["name"],
                                size=14,
                                weight=ft.FontWeight.W_600,
                                expand=True,
                            ),
                            ft.Container(
                                SecondaryText("Context", size=11),
                                width=50,
                                alignment=ft.alignment.center_right,
                            ),
                            ft.Container(
                                SecondaryText("In $/M", size=11),
                                width=60,
                                alignment=ft.alignment.center_right,
                            ),
                            ft.Container(
                                SecondaryText("Out $/M", size=11),
                                width=60,
                                alignment=ft.alignment.center_right,
                            ),
                        ],
                        spacing=Theme.Spacing.SM,
                    ),
                    padding=ft.padding.symmetric(
                        horizontal=Theme.Spacing.MD, vertical=8
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
                )

                # Model rows
                model_rows = []
                for model in sorted_models:
                    model_id = model.get("model_id", "")
                    context = model.get("context_window", 0)
                    input_price = model.get("input_price")
                    output_price = model.get("output_price")

                    row = ft.Container(
                        content=ft.Row(
                            [
                                ft.Container(
                                    ft.Text(
                                        model_id,
                                        size=12,
                                        weight=ft.FontWeight.W_500,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    expand=True,
                                    tooltip=model_id,
                                ),
                                ft.Container(
                                    SecondaryText(_format_context(context), size=12),
                                    width=50,
                                    alignment=ft.alignment.center_right,
                                ),
                                ft.Container(
                                    SecondaryText(_format_price(input_price), size=12),
                                    width=60,
                                    alignment=ft.alignment.center_right,
                                ),
                                ft.Container(
                                    SecondaryText(_format_price(output_price), size=12),
                                    width=60,
                                    alignment=ft.alignment.center_right,
                                ),
                            ],
                            spacing=Theme.Spacing.SM,
                        ),
                        bgcolor=ft.Colors.SURFACE,
                        padding=ft.padding.symmetric(
                            horizontal=Theme.Spacing.MD, vertical=6
                        ),
                    )
                    model_rows.append(row)

                # Combine vendor header and models
                vendor_section = ft.Container(
                    content=ft.Column([vendor_header, *model_rows], spacing=0),
                    border_radius=Theme.Components.CARD_RADIUS,
                    border=ft.border.all(1, ft.Colors.OUTLINE),
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    expand=True,
                )
                vendor_sections.append(vendor_section)

            # Arrange in rows of 2
            rows = []
            for i in range(0, len(vendor_sections), 2):
                row_items = vendor_sections[i : i + 2]
                rows.append(ft.Row(row_items, spacing=Theme.Spacing.MD))

            self.content = ft.Column(
                [
                    SectionHeader("Featured Models"),
                    ft.Container(height=Theme.Spacing.SM),
                    ft.Column(rows, spacing=Theme.Spacing.MD),
                ],
                spacing=0,
            )
        self.padding = Theme.Spacing.MD
