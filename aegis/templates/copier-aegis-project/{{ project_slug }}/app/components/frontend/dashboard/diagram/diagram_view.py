"""
Diagram View component for architecture visualization.

Displays components as interactive nodes with connection lines
in either tree or radial layout.
"""

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.services.system.models import ComponentStatus

from .diagram_canvas import DiagramCanvas
from .diagram_node import DiagramNode
from .layout import (
    LayoutType,
    calculate_positions,
    get_connections,
)


class DiagramView(ft.Container):
    """
    Main diagram view container with layout toggle.

    Features:
    - Tree and radial layout modes
    - Interactive nodes with click-to-modal
    - Bezier connection lines
    - Responsive sizing
    """

    def __init__(self) -> None:
        """Initialize the diagram view."""
        super().__init__()
        self._layout_type = LayoutType.RADIAL
        self._components: dict[str, ComponentStatus] = {}
        self._nodes: dict[str, DiagramNode] = {}

        # Node size (height - width is size + 80)
        self._node_size = 80

        # Scale for converting normalized coords (-1 to 1) to pixels
        # Diagram spans ~2x this value in each direction
        self._scale = 550

        # Build initial UI
        self._build()

    def _build(self) -> None:
        """Build the diagram view UI."""
        # Layout toggle button
        self._layout_toggle = ft.IconButton(
            icon=ft.Icons.ACCOUNT_TREE,
            tooltip="Switch to Tree Layout",
            icon_size=20,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            on_click=self._toggle_layout,
        )

        # Header with layout toggle - full width
        header = ft.Row(
            [
                SecondaryText("Architecture"),
                self._layout_toggle,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Diagram size based on scale (coords go from 0 to 2*scale)
        diagram_size = self._scale * 2

        # Canvas for connection lines (underneath nodes)
        self._canvas = DiagramCanvas(diagram_size, diagram_size)

        # Stack for nodes (on top of canvas)
        self._node_stack = ft.Stack(
            controls=[],
            width=diagram_size,
            height=diagram_size,
        )

        # Diagram area - canvas and nodes stacked
        self._diagram_area = ft.Stack(
            controls=[
                self._canvas,
                self._node_stack,
            ],
            width=diagram_size,
            height=diagram_size,
        )

        # Header container
        header_container = ft.Container(
            content=header,
            padding=ft.padding.only(left=16, right=8, top=12, bottom=12),
            bgcolor=ft.Colors.SURFACE,
            border_radius=ft.border_radius.only(top_left=12, top_right=12),
        )

        # Container styling - full bleed
        self.content = ft.Column(
            [
                header_container,
                ft.Container(
                    content=self._diagram_area,
                    expand=True,
                    alignment=ft.alignment.top_center,
                ),
            ],
            spacing=0,
            expand=True,
        )
        self.bgcolor = ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        self.border_radius = 12
        self.expand = True
        self.padding = 0

    def _toggle_layout(self, e: ft.ControlEvent) -> None:
        """Toggle between tree and radial layouts."""
        if self._layout_type == LayoutType.TREE:
            self._layout_type = LayoutType.RADIAL
            self._layout_toggle.icon = ft.Icons.ACCOUNT_TREE
            self._layout_toggle.tooltip = "Switch to Tree Layout"
        else:
            self._layout_type = LayoutType.TREE
            self._layout_toggle.icon = ft.Icons.BLUR_CIRCULAR
            self._layout_toggle.tooltip = "Switch to Radial Layout"

        # Redraw with new layout
        self._draw_diagram()

        if e.page:
            self.update()

    def _normalized_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """
        Convert normalized coordinates (-1 to 1) to pixel coordinates.

        Args:
            x: Normalized x coordinate (-1 to 1)
            y: Normalized y coordinate (-1 to 1)

        Returns:
            (pixel_x, pixel_y) tuple
        """
        # Center horizontally, but position vertically near top
        center_x = self._scale
        center_y = self._scale * 0.6  # Shift up

        # Convert normalized to pixel
        pixel_x = center_x + (x * self._scale)
        pixel_y = center_y + (y * self._scale)

        return pixel_x, pixel_y

    def _draw_diagram(self) -> None:
        """Draw the complete diagram with nodes and connections."""
        if not self._components:
            return

        # Clear previous state
        self._canvas.clear()
        self._node_stack.controls.clear()
        self._nodes.clear()

        # Set curve style based on layout type
        is_tree = self._layout_type == LayoutType.TREE
        self._canvas.set_tree_style(is_tree)

        # Calculate node positions
        positions = calculate_positions(self._components, self._layout_type)

        # Create nodes and add to stack
        position_map: dict[str, tuple[float, float]] = {}
        for pos in positions:
            # Convert to pixel coordinates
            px, py = self._normalized_to_pixel(pos.x, pos.y)

            # Store position for connection drawing
            position_map[pos.component_name] = (px, py)

            # Create and position the node
            node = DiagramNode(
                component_name=pos.component_name,
                component_data=pos.component_data,
                size=self._node_size,
            )
            self._nodes[pos.component_name] = node

            # Position node (centered on coordinates)
            # Node actual width is size + 80, height is size
            node_width = self._node_size + 80
            node_height = self._node_size
            node_container = ft.Container(
                content=node,
                left=px - (node_width / 2),
                top=py - (node_height / 2),
            )
            self._node_stack.controls.append(node_container)

        # Get connections and draw them
        connections = get_connections(self._components)
        for parent_name, child_name in connections:
            if parent_name in position_map and child_name in position_map:
                start = position_map[parent_name]
                end = position_map[child_name]

                # Tree layout: all connections from backend start at bottom center
                if is_tree and parent_name == "backend":
                    start = (start[0], start[1] + self._node_size / 2)

                child_data = self._components.get(child_name)
                if child_data:
                    self._canvas.add_connection(start, end, child_data)

        # Render connections
        self._canvas.draw_connections()

    def update_components(self, components: dict[str, ComponentStatus]) -> None:
        """
        Update the diagram with new component data.

        Args:
            components: Dictionary mapping component names to their status
        """
        self._components = components
        self._draw_diagram()
