"""
Diagram Node component for visualizing individual components.

Each node represents a component in the architecture diagram with
click-to-open-modal functionality and hover effects.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.services.system.ui import get_component_label, get_component_subtitle

from ..cards.card_utils import _open_modal, get_ai_engine_display

# Display names per component id. The id itself is what opens the modal:
# cards, overview rows and diagram nodes all use the health-tree id, and
# the modal registers under it, so there is no second name to keep in step.
# Subtitles are generated dynamically via get_component_label()
COMPONENT_NAMES: dict[str, str] = {
    "backend": "Server",
    "database": "Database",
    "cache": "Cache",
    "worker": "Worker",
    "ingress": "Ingress",
    "ollama": "Inference",
    "scheduler": "Scheduler",
    "storage": "Storage",
    "service_ai": "AI Service",
    "service_auth": "Auth Service",
    "service_comms": "Comms Service",
    "frontend": "Frontend",
}


def get_status_color(status: ComponentStatusType) -> str:
    """Get the status dot color for a component status."""
    if status == ComponentStatusType.HEALTHY:
        return Theme.Colors.SUCCESS
    elif status == ComponentStatusType.WARNING:
        return Theme.Colors.WARNING
    elif status == ComponentStatusType.INFO:
        return Theme.Colors.INFO
    else:
        return Theme.Colors.ERROR


def get_border_color(status: ComponentStatusType) -> str:
    """Get the border color for a component status (matches card styling)."""
    if status == ComponentStatusType.HEALTHY:
        return ft.Colors.OUTLINE  # Subtle gray for healthy
    elif status == ComponentStatusType.WARNING:
        return Theme.Colors.WARNING
    elif status == ComponentStatusType.INFO:
        return Theme.Colors.INFO
    else:
        return Theme.Colors.ERROR


class DiagramNode(ft.Container):
    """
    A visual node representing a component in the diagram.

    Card-style design with:
    - Icon in top-left
    - Status dot in top-right corner
    - Name and subtitle text
    - Status-colored border
    - Hover effects
    - Click to open detail modal
    """

    def __init__(
        self,
        component_name: str,
        component_data: ComponentStatus,
        size: int = 90,
    ) -> None:
        """
        Initialize a diagram node.

        Args:
            component_name: The component identifier (e.g., "backend", "database")
            component_data: The component's status data
            size: Node width in pixels (height is proportional)
        """
        super().__init__()
        self._component_name = component_name
        self._component_data = component_data
        self._size = size

        self._display_name = COMPONENT_NAMES.get(
            component_name, component_name.replace("_", " ").title()
        )
        self._subtitle = self._get_subtitle(component_name, component_data)

        # Status colors
        self._status_color = get_status_color(component_data.status)  # For dot
        self._border_color = get_border_color(component_data.status)  # For border

        # Build the node content
        self._build()

    def _get_subtitle(
        self, component_name: str, component_data: ComponentStatus
    ) -> str:
        """Get subtitle from metadata or fall back to static label."""
        metadata = component_data.metadata or {}

        # Dynamic subtitles from metadata
        if component_name == "service_ai":
            return get_ai_engine_display(metadata)
        elif component_name == "service_auth":
            return "JWT Authentication"
        elif component_name in ("ingress", "worker", "service_insights"):
            return get_component_subtitle(component_name, metadata)

        # Fall back to static label
        return get_component_label(component_name)

    def _build(self) -> None:
        """Build the node visual content."""
        # Title and subtitle (upper-left)
        title_subtitle = ft.Column(
            [
                ft.Text(
                    self._display_name,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_SURFACE,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Text(
                    self._subtitle,
                    size=10,
                    weight=ft.FontWeight.W_400,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=2,
        )

        # Status indicator dot (upper-right)
        status_dot = ft.Container(
            width=10,
            height=10,
            border_radius=5,
            bgcolor=self._status_color,
        )

        # Top row: title/subtitle left, status dot right
        top_row = ft.Row(
            [title_subtitle, status_dot],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Content column
        content = ft.Column(
            [top_row],
            spacing=0,
        )

        # Container styling - card-like with padding
        self.content = ft.Container(
            content=content,
            padding=ft.padding.all(12),
        )
        self.width = self._size + 80  # Wider cards to match reference
        self.height = self._size
        self.bgcolor = ft.Colors.SURFACE
        self.border = ft.border.all(1, self._border_color)
        self.border_radius = 10
        self.animate = ft.Animation(150, ft.AnimationCurve.EASE_OUT)

        # Event handlers
        self.on_hover = self._handle_hover
        self.on_click = self._handle_click

    def _handle_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state changes (matches CardContainer pattern)."""
        if e.data == "true":
            # Hover enter - thicker border with padding compensation
            self.border = ft.border.all(3, self._border_color)
            self.padding = ft.padding.all(-2)  # Compensate for border increase
            self.scale = 1.02
        else:
            # Hover exit - restore normal state
            self.border = ft.border.all(1, self._border_color)
            self.padding = ft.padding.all(0)
            self.scale = 1.0

        if e.page:
            self.update()

    def _handle_click(self, e: ft.ControlEvent) -> None:
        """Handle click to open detail modal."""
        if not e.page:
            return

        _open_modal(self._component_name, self._component_data, e.page)

    def update_data(self, component_data: ComponentStatus) -> None:
        """
        Update the node with new component data.

        Args:
            component_data: New component status data
        """
        self._component_data = component_data
        self._status_color = get_status_color(component_data.status)
        self._build()
