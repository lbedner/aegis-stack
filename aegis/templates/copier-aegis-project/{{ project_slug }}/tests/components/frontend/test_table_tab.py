"""A Flet table of rows (``table_tab.TableTab``), as htmx's ``data_table``."""

import flet as ft

from app.components.frontend.dashboard.modals.table_tab import TableTab


def _first_cells(tab: TableTab) -> list[ft.Control]:
    """Each row's first cell, as the table was handed it."""
    return [cells[0] for cells in tab.content.controls[0]._rows]


def test_a_child_row_sits_indented_under_the_row_it_belongs_to() -> None:
    """A row's parts (``child``), as htmx indents them: a call a script
    made under the script's call."""
    rows = [
        {"tool": "run_code", "result": "OK"},
        {"tool": "lookup", "result": "OK", "child": True},
    ]

    parent, child = _first_cells(TableTab(rows, [("Tool", "tool", None)], ""))

    assert not isinstance(parent, ft.Container) or not parent.padding
    assert isinstance(child, ft.Container) and child.padding.left > 0
