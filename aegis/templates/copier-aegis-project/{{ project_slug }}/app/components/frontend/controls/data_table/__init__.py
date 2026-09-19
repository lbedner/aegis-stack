"""The dashboard's table: one cell toolkit, the parts, and the table.

Split out of one 1,082-line module. Everything callers already imported
from ``controls.data_table`` is re-exported here, so the move is
invisible at every call site.
"""

from .cells import (
    CELL_ELLIPSIS_KWARGS,
    CELL_TOOLTIPS_ENABLED,
    PICKER_GUTTER_WIDTH,
    DataTableColumn,
    build_cell,
    cell_text,
    get_alignment,
    header_cell,
    style_cell,
)
from .parts import (
    DataTableHeader,
    DataTableRow,
    SelectionCheckbox,
    set_revealed,
)
from .table import DataTable

__all__ = [
    "CELL_ELLIPSIS_KWARGS",
    "CELL_TOOLTIPS_ENABLED",
    "PICKER_GUTTER_WIDTH",
    "DataTable",
    "DataTableColumn",
    "DataTableHeader",
    "DataTableRow",
    "SelectionCheckbox",
    "build_cell",
    "cell_text",
    "get_alignment",
    "header_cell",
    "set_revealed",
    "style_cell",
]
