"""
Expand Arrow Control

Reusable expand/collapse arrow indicator for expandable UI elements.
"""

import flet as ft

# Fixed width for an expand-arrow gutter cell - shared by every table that
# grows one (ExpandableDataTable, and DataTable's own expandable_content),
# so both line their arrow columns up identically instead of picking their
# own number.
EXPAND_ICON_WIDTH = 24


class ExpandArrow(ft.Icon):
    """
    Expand/collapse arrow indicator.

    Displays ARROW_RIGHT when collapsed, ARROW_DROP_DOWN when expanded.
    Consistent styling across all expandable components.

    Usage:
        arrow = ExpandArrow()
        # Later, toggle state:
        arrow.set_expanded(True)
        arrow.update()
    """

    def __init__(self, expanded: bool = False) -> None:
        """
        Initialize expand arrow.

        Args:
            expanded: Initial expansion state (default: collapsed)
        """
        super().__init__(
            name=ft.Icons.ARROW_DROP_DOWN if expanded else ft.Icons.ARROW_RIGHT,
            size=24,
            color=ft.Colors.OUTLINE,
        )
        self._expanded = expanded

    @property
    def expanded(self) -> bool:
        """Get current expansion state."""
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        """
        Set expansion state and update icon.

        Args:
            expanded: New expansion state
        """
        self._expanded = expanded
        self.name = ft.Icons.ARROW_DROP_DOWN if expanded else ft.Icons.ARROW_RIGHT

    def toggle(self) -> bool:
        """
        Toggle expansion state.

        Returns:
            New expansion state after toggle
        """
        self.set_expanded(not self._expanded)
        return self._expanded
