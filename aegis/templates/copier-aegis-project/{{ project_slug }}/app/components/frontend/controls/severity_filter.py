"""
Severity filter control for activity feeds.

Row of clickable pill containers for filtering events by severity level.
Fixed-width pills avoid the layout shift caused by SegmentedButton checkmarks.
"""

from collections.abc import Callable

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

# Severity levels: (label, min_severity, color)
_SEVERITY_OPTIONS: list[tuple[str, int, str]] = [
    ("All", 0, Theme.Colors.ACCENT),
    ("Info", 1, Theme.Colors.INFO),
    ("Warning", 2, Theme.Colors.WARNING),
    ("Error", 3, Theme.Colors.ERROR),
]

_PILL_WIDTH = 64
_PILL_HEIGHT = 28
_SELECTED_OPACITY = 0.15


class SeverityFilter(ft.Row):
    """Row of pill-shaped buttons for filtering by severity level.

    Reports the selected minimum severity via on_change callback.
    """

    def __init__(
        self,
        on_change: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_change = on_change
        self._selected_severity = 0
        self._pills: list[ft.Container] = []

        for label, severity, color in _SEVERITY_OPTIONS:
            pill = self._build_pill(label, severity, color)
            self._pills.append(pill)

        self.controls = self._pills
        self.spacing = Theme.Spacing.XS

    @property
    def selected_severity(self) -> int:
        """Current minimum severity threshold."""
        return self._selected_severity

    @property
    def selected_color(self) -> str:
        """Color of the currently selected severity level."""
        for _label, severity, color in _SEVERITY_OPTIONS:
            if severity == self._selected_severity:
                return color
        return Theme.Colors.ACCENT

    def _build_pill(self, label: str, severity: int, color: str) -> ft.Container:
        """Build a single pill container."""
        is_selected = severity == self._selected_severity
        return ft.Container(
            content=ft.Text(
                label,
                size=Theme.Typography.BODY_SMALL,
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
                color=color if is_selected else Theme.Colors.TEXT_SECONDARY,
                text_align=ft.TextAlign.CENTER,
            ),
            width=_PILL_WIDTH,
            height=_PILL_HEIGHT,
            alignment=ft.alignment.center,
            border_radius=Theme.Components.BADGE_RADIUS,
            bgcolor=(
                ft.Colors.with_opacity(_SELECTED_OPACITY, color)
                if is_selected
                else ft.Colors.TRANSPARENT
            ),
            on_click=lambda e, sev=severity: self._handle_click(sev),
            ink=True,
        )

    def _handle_click(self, severity: int) -> None:
        """Handle pill click — update selection and notify."""
        if severity == self._selected_severity:
            return

        self._selected_severity = severity

        # Rebuild all pills to reflect new selection state
        for i, (_label, sev, color) in enumerate(_SEVERITY_OPTIONS):
            is_selected = sev == self._selected_severity
            pill = self._pills[i]
            pill.bgcolor = (
                ft.Colors.with_opacity(_SELECTED_OPACITY, color)
                if is_selected
                else ft.Colors.TRANSPARENT
            )
            text = pill.content
            text.color = color if is_selected else Theme.Colors.TEXT_SECONDARY

        if self.page:
            self.update()

        if self._on_change:
            self._on_change(self._selected_severity)
