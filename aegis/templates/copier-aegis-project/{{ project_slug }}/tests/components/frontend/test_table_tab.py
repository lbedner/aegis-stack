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


def test_a_row_opens_to_its_detail() -> None:
    """``detail`` builds what a row opens to, as htmx's ``data_table``
    does; built when the row is first opened, not with the table."""
    rows = [{"tool": "lookup", "id": "1"}, {"tool": "save", "id": "2"}]
    opened: list[str] = []

    def detail(row: dict[str, str]) -> ft.Control:
        opened.append(row["id"])
        return ft.Text(row["tool"])

    tab = TableTab(rows, [("Tool", "tool", None)], "", detail=detail)
    assert opened == []

    shown = tab.content.controls[0]._expandable_content(1)

    assert opened == ["2"] and shown.value == "save"
