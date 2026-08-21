"""
Diagram Canvas for drawing connection lines between nodes.

Uses Flet's Canvas with bezier curves for smooth connection rendering.
"""

import flet as ft
import flet.canvas as cv

from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus, ComponentStatusType


def get_status_color(status: ComponentStatusType) -> str:
    """Get the color for a component status."""
    if status == ComponentStatusType.HEALTHY:
        return Theme.Colors.SUCCESS
    elif status == ComponentStatusType.WARNING:
        return Theme.Colors.WARNING
    elif status == ComponentStatusType.INFO:
        return Theme.Colors.INFO
    else:
        return Theme.Colors.ERROR


class DiagramCanvas(ft.Container):
    """
    Canvas for drawing bezier connection lines between diagram nodes.

    Connection colors are based on the child node's status.
    """

    def __init__(self, width: float, height: float) -> None:
        """Initialize the diagram canvas."""
        super().__init__()
        self._width = width
        self._height = height
        self._connections: list[
            tuple[tuple[float, float], tuple[float, float], str]
        ] = []
        self._tree_style = False  # Use radial style by default

        # Build initial empty canvas
        self._build()

    def set_tree_style(self, tree_style: bool) -> None:
        """Set whether to use tree-style curves (vs radial)."""
        self._tree_style = tree_style

    def _build(self) -> None:
        """Build the canvas container."""
        self._canvas = cv.Canvas(
            shapes=[],
            width=self._width,
            height=self._height,
        )

        self.content = self._canvas
        self.width = self._width
        self.height = self._height

    def clear(self) -> None:
        """Clear all connections from the canvas."""
        self._connections = []
        self._canvas.shapes = []

    def add_connection(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        child_data: ComponentStatus,
    ) -> None:
        """
        Add a connection line between two points.

        Args:
            start: (x, y) start point in pixels
            end: (x, y) end point in pixels
            child_data: ComponentStatus of the child node (determines color)
        """
        color = get_status_color(child_data.status)
        self._connections.append((start, end, color))

    def draw_connections(self) -> None:
        """Draw all connections as bezier curves on the canvas."""
        shapes: list[cv.Path] = []

        for start, end, color in self._connections:
            path = self._create_bezier_path(start, end, color)
            shapes.append(path)

        self._canvas.shapes = shapes

    def _create_bezier_path(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        color: str,
    ) -> cv.Path:
        """
        Create a bezier curve path between two points.

        Uses a smooth curve with control points calculated based on
        the direction of the connection.

        Args:
            start: (x, y) start point
            end: (x, y) end point
            color: Line color

        Returns:
            Canvas Path object with bezier curve
        """
        x1, y1 = start
        x2, y2 = end

        dx = x2 - x1
        dy = y2 - y1

        if self._tree_style:
            # Tree-style curves: drop down vertically, then curve to target
            cp1_x = x1
            cp1_y = y1 + abs(dy) * 0.5
            cp2_x = x2
            cp2_y = y2 - abs(dy) * 0.3
        else:
            # Radial-style curves: smooth curve based on direction
            distance = (dx**2 + dy**2) ** 0.5
            curvature = min(distance * 0.4, 80)

            if abs(dy) > abs(dx):
                cp1_x = x1
                cp1_y = y1 + curvature if y2 > y1 else y1 - curvature
                cp2_x = x2
                cp2_y = y2 - curvature if y2 > y1 else y2 + curvature
            else:
                cp1_x = x1 + curvature if x2 > x1 else x1 - curvature
                cp1_y = y1
                cp2_x = x2 - curvature if x2 > x1 else x2 + curvature
                cp2_y = y2

        # Create the bezier path
        path = cv.Path(
            elements=[
                cv.Path.MoveTo(x1, y1),
                cv.Path.CubicTo(cp1_x, cp1_y, cp2_x, cp2_y, x2, y2),
            ],
            paint=ft.Paint(
                color=ft.Colors.with_opacity(0.6, color),
                stroke_width=2,
                style=ft.PaintingStyle.STROKE,
                stroke_cap=ft.StrokeCap.ROUND,
            ),
        )

        return path
