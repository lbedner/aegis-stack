"""
Card Factory Utilities

Provides common patterns and utilities for creating dashboard card components,
reducing duplication across different card types.
"""

import flet as ft

from app.components.frontend.controls import (
    LabelText,
    MetricText,
    PrimaryText,
    SecondaryText,
)


class CardFactory:
    """Factory class for creating common card components and patterns."""

    @staticmethod
    def create_stats_row(
        label: str, value: str, value_color: str | None = None
    ) -> ft.Row:
        """
        Create a standardized statistics row with label and value.

        Args:
            label: The label text (e.g., "Active Workers:")
            value: The value text (e.g., "2")
            value_color: Optional color for the value text

        Returns:
            Row with label and value properly aligned
        """
        value_control = LabelText(value)
        if value_color:
            value_control.color = value_color

        return ft.Row(
            [
                SecondaryText(f"{label}:"),
                value_control,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    @staticmethod
    def create_metric_indicator(
        label: str,
        value: str,
        icon: str,
        color: str,
        width: int = 100,
        height: int = 70,
    ) -> ft.Container:
        """
        Create a standardized metric indicator box.

        Args:
            label: Label for the metric (e.g., "LOAD_TEST")
            value: Value to display (e.g., "0 jobs")
            icon: Emoji icon for the metric
            color: Border and accent color
            width: Width of the indicator
            height: Height of the indicator

        Returns:
            Container with the metric indicator
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(icon, size=12),
                            LabelText(label.upper()),
                        ],
                        spacing=5,
                    ),
                    ft.Container(height=2, bgcolor=color, border_radius=1),
                    LabelText(value),
                ],
                spacing=2,
            ),
            padding=ft.padding.all(8),
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.all(1, color),
            border_radius=8,
            width=width,
            height=height,
        )

    @staticmethod
    def create_progress_indicator(
        label: str, value: float, details: str, color: str
    ) -> ft.Container:
        """
        Create a progress indicator with label, progress bar, and details.

        Args:
            label: Label for the progress indicator
            value: Progress value (0-100)
            details: Additional details text
            color: Color for the progress bar

        Returns:
            Container with the progress indicator
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        label,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600,
                    ),
                    ft.Container(
                        content=ft.ProgressBar(
                            value=value / 100.0,
                            height=8,
                            color=color,
                            bgcolor=ft.Colors.GREY_300,
                            border_radius=4,
                        ),
                        margin=ft.margin.only(top=4, bottom=4),
                    ),
                    ft.Row(
                        [
                            ft.Text(
                                f"{value:.1f}%",
                                size=16,
                                weight=ft.FontWeight.W_700,
                                color=ft.Colors.ON_SURFACE,
                            ),
                            ft.Text(
                                details,
                                size=14,
                                color=ft.Colors.GREY_600,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=2,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            expand=True,
        )

    @staticmethod
    def create_circular_gauge(
        label: str, value: float, unit: str, color: str
    ) -> ft.Container:
        """
        Create a circular gauge-style metric display.

        Args:
            label: Label for the gauge
            value: Numeric value to display
            unit: Unit text (e.g., "MB", "%")
            color: Color for the gauge border

        Returns:
            Container with the circular gauge
        """
        return ft.Container(
            content=ft.Column(
                [
                    LabelText(label),
                    ft.Container(
                        content=ft.Column(
                            [
                                MetricText(f"{value:.1f}"),
                                LabelText(unit),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=0,
                        ),
                        width=60,
                        height=60,
                        bgcolor=ft.Colors.with_opacity(0.1, color),
                        border=ft.border.all(2, color),
                        border_radius=30,
                        padding=ft.padding.all(4),
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.padding.all(8),
        )

    @staticmethod
    def create_section_with_title(
        title: str, content: list[ft.Control], width: int, spacing: int = 8
    ) -> ft.Container:
        """
        Create a section container with title and content.

        Args:
            title: Section title
            content: List of controls for the section content
            width: Width of the section
            spacing: Spacing between elements

        Returns:
            Container with titled section
        """
        section_content = [
            PrimaryText(title),
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
        ]
        section_content.extend(content)

        return ft.Container(
            content=ft.Column(
                section_content,
                spacing=spacing,
                alignment=ft.MainAxisAlignment.START,
            ),
            width=width,
            padding=ft.padding.all(16),
            alignment=ft.alignment.top_left,
        )
