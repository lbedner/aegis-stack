"""
Base Modal Class for Component Detail Dialogs

Provides a unified base class for all component detail modals with consistent
styling, layout, and behavior across the Overseer dashboard.
"""

import flet as ft

from app.components.frontend.controls import H2Text, Tag
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus, ComponentStatusType

from .modal_constants import ModalLayout


class BaseDetailDialog(ft.AlertDialog):
    """
    Base class for all component detail modals.

    Provides consistent title formatting, status badges, layout structure,
    and close behavior. Child classes need only provide sections and
    customization parameters.

    Usage:
        class MyDetailDialog(BaseDetailDialog):
            def __init__(self, component_data: ComponentStatus):
                sections = [
                    MyOverviewSection(component_data.metadata),
                    ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                    MyStatsSection(component_data),
                ]

                super().__init__(
                    component_data=component_data,
                    title_text="My Component Details",
                    sections=sections,
                )
    """

    def __init__(
        self,
        component_data: ComponentStatus,
        title_text: str,
        sections: list[ft.Control],
        width: int = ModalLayout.DEFAULT_WIDTH,
        height: int = ModalLayout.DEFAULT_HEIGHT,
    ) -> None:
        """
        Initialize the base detail modal.

        Args:
            component_data: ComponentStatus containing component health and metrics
            title_text: Title text (e.g., "Scheduler Details")
            sections: List of section controls to display in modal body
            width: Modal width in pixels (default: 900)
            height: Modal height in pixels (default: 700)
        """
        self.component_data = component_data
        self.title_text = title_text

        # Build modal content with scrollable sections
        content = ft.Container(
            content=ft.Column(
                sections,
                spacing=0,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=width,
            height=height,
            border=ft.border.all(1, ft.Colors.OUTLINE),  # Neutral border
            border_radius=Theme.Components.CARD_RADIUS,  # Rounded corners like cards
        )

        # Initialize dialog with consistent styling
        super().__init__(
            modal=False,
            title=self._create_title(),
            content=content,
            actions=[
                ft.TextButton("Close", on_click=self._close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=ft.Colors.SURFACE,
        )

    def _create_title(self) -> ft.Control:
        """
        Create the modal title with status badge.

        Returns a Row containing the title text with icon and a status badge
        using theme-aware colors.
        """
        status_color = self._get_status_color()

        return ft.Row(
            [
                H2Text(self.title_text),
                Tag(
                    text=self.component_data.status.value.upper(),
                    color=status_color,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    def _get_status_color(self) -> str:
        """
        Map component status to theme color.

        Returns:
            Theme color constant based on component status
        """
        status_map = {
            ComponentStatusType.HEALTHY: Theme.Colors.SUCCESS,
            ComponentStatusType.INFO: Theme.Colors.INFO,
            ComponentStatusType.WARNING: Theme.Colors.WARNING,
            ComponentStatusType.UNHEALTHY: Theme.Colors.ERROR,
        }
        return status_map.get(self.component_data.status, ft.Colors.ON_SURFACE_VARIANT)

    def _close(self, e: ft.ControlEvent) -> None:
        """Close the modal dialog."""
        self.open = False
        e.page.update()
