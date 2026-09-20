"""Markdown tables, measured and drawn in ANSI.

A table is the one element that needs to see all of its children
before it can size a single column, so it carries the width pass
and the separator drawing that nothing else needs.
"""

from collections.abc import Callable
from typing import Any


class TableRenderMixin:
    """Table rendering for ``TerminalRenderer``.

    ``render_children`` comes from marko's ``Renderer`` and
    ``_get_content`` from the renderer itself; both are declared so
    this module type checks on its own.
    """

    render_children: Callable[[Any], str]
    _get_content: Callable[[Any], str]

    def render_table(self, element) -> str:
        """
        Render table with aligned columns using two-pass approach.

        Args:
            element: Table element from GFM

        Returns:
            Formatted table string
        """
        rows = element.children
        if not rows:
            return ""

        # First pass: render all cells and collect metadata
        rendered_rows = []
        for row in rows:
            # Skip non-element children (strings from malformed parsing)
            if not hasattr(row, "children"):
                continue
            rendered_cells = []
            for cell in row.children:
                # Skip non-element cells
                if not hasattr(cell, "children"):
                    continue
                content = self.render_children(cell)
                is_header = getattr(cell, "header", False)
                rendered_cells.append((content, is_header))
            if rendered_cells:
                rendered_rows.append(rendered_cells)

        if not rendered_rows:
            return ""

        # Calculate column widths from rendered content
        col_widths = self._calculate_widths_from_rendered(rendered_rows)

        # Second pass: format rows with alignment and styling
        result = []
        for i, rendered_cells in enumerate(rendered_rows):
            row_parts = []
            for j, (content, is_header) in enumerate(rendered_cells):
                # Strip ANSI for padding calculation
                clean = self._strip_ansi(content)
                padding = col_widths[j] - len(clean)

                # Apply header styling
                styled = f"\033[1;36m{content}\033[0m" if is_header else content

                padded = styled + (" " * padding)
                row_parts.append(padded)

            row_text = "| " + " | ".join(row_parts) + " |"
            result.append(row_text)

            # Add separator after header row
            if i == 0:
                separator = self._render_table_separator(col_widths)
                result.append(separator)

        return "\n" + "\n".join(result) + "\n\n"

    def render_table_row(self, element) -> str:
        """
        Render table row - return empty as table handles rendering.

        Args:
            element: TableRow element

        Returns:
            Empty string (rendering handled by render_table)
        """
        # Table rendering is handled entirely by render_table
        # This method must exist for marko but returns empty
        return ""

    def render_table_cell(self, element) -> str:
        """
        Render cell content without styling.

        Args:
            element: TableCell element

        Returns:
            Plain cell content (styling applied by render_table)
        """
        # Just render children (safely), styling happens in render_table
        return self._get_content(element)

    def _calculate_widths_from_rendered(
        self, rendered_rows: list[list[tuple[str, bool]]]
    ) -> list[int]:
        """
        Calculate column widths from pre-rendered cells.

        Args:
            rendered_rows: List of rows, each row is list of (content, is_header)

        Returns:
            List of column widths
        """
        col_widths = []
        max_cols = max(len(row) for row in rendered_rows)

        for col_idx in range(max_cols):
            max_width = 0
            for row in rendered_rows:
                if col_idx < len(row):
                    content, _ = row[col_idx]
                    clean = self._strip_ansi(content)
                    max_width = max(max_width, len(clean))
            col_widths.append(max_width)

        return col_widths

    def _strip_ansi(self, text: str) -> str:
        """
        Strip ANSI escape codes for width calculation.

        Args:
            text: Text with ANSI codes

        Returns:
            Clean text without ANSI codes
        """
        import re

        ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
        return ansi_pattern.sub("", text)

    def _render_table_separator(self, col_widths: list[int]) -> str:
        """
        Render separator line between header and body.

        Args:
            col_widths: List of column widths

        Returns:
            Separator line string
        """
        segments = ["-" * (width + 2) for width in col_widths]
        return "|" + "|".join(segments) + "|"
