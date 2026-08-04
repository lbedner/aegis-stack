"""Tests for the shared table controls' column sizing contract.

Both table families (plain and expandable) size their cells from the same
``DataTableColumn``, so they are held to the same contract here. They drifted
once: a flex-weight experiment landed in one and not the other, and every
width-less column in an expandable table collapsed to a few pixels, wrapping
its text one character per line.
"""

import flet as ft

from app.components.frontend.controls.data_table import (
    DataTable,
    DataTableColumn,
    DataTableHeader,
    DataTableRow,
)
from app.components.frontend.controls.expandable_data_table import (
    EXPAND_ICON_WIDTH,
    ExpandableRow,
    ExpandableTableHeader,
    ExpandableTableRow,
)

COLUMNS = [
    DataTableColumn("Ticker", width=90),
    DataTableColumn("Name"),
    DataTableColumn("Market Value", width=150, alignment="right"),
]
VALUES = ["6643", "FID FRDM 2040", "$1.00"]


def _cells(container: ft.Container) -> list[ft.Container]:
    row = container.content
    assert isinstance(row, ft.Row)
    return list(row.controls)


def _expandable_cells(container: ft.Container) -> list[ft.Container]:
    """Data cells of an expandable row, minus the leading arrow gutter."""
    cells = _cells(container)
    assert cells[0].width == EXPAND_ICON_WIDTH, "expected the arrow gutter first"
    return cells[1:]


def _expandable_row_cells(row_container: ft.Container) -> list[ft.Container]:
    gesture = row_container.content.controls[0]
    return _expandable_cells(gesture.content)


class TestColumnSizing:
    """width=N is a fixed pixel width; width=None fills remaining space."""

    def test_header_fixed_columns_use_pixel_width(self) -> None:
        cells = _cells(DataTableHeader(COLUMNS))
        assert cells[0].width == 90
        assert not cells[0].expand
        assert cells[2].width == 150
        assert not cells[2].expand

    def test_header_widthless_column_expands(self) -> None:
        cells = _cells(DataTableHeader(COLUMNS))
        assert cells[1].width is None
        assert cells[1].expand

    def test_row_fixed_columns_use_pixel_width(self) -> None:
        cells = _cells(DataTableRow(COLUMNS, VALUES))
        assert cells[0].width == 90
        assert not cells[0].expand
        assert cells[2].width == 150
        assert not cells[2].expand

    def test_row_widthless_column_expands(self) -> None:
        cells = _cells(DataTableRow(COLUMNS, VALUES))
        assert cells[1].width is None
        assert cells[1].expand


class TestExpandableColumnSizing:
    """The expandable table obeys the same contract as the plain one."""

    def test_header_fixed_columns_use_pixel_width(self) -> None:
        cells = _expandable_cells(ExpandableTableHeader(COLUMNS))
        assert cells[0].width == 90
        assert not cells[0].expand
        assert cells[2].width == 150
        assert not cells[2].expand

    def test_header_widthless_column_expands(self) -> None:
        cells = _expandable_cells(ExpandableTableHeader(COLUMNS))
        assert cells[1].width is None
        assert cells[1].expand

    def test_row_fixed_columns_use_pixel_width(self) -> None:
        row = ExpandableTableRow(
            COLUMNS,
            ExpandableRow(cells=VALUES, expanded_content=ft.Text("detail")),
            is_expanded=False,
            on_toggle=lambda _e: None,
        )
        cells = _expandable_row_cells(row)
        assert cells[0].width == 90
        assert not cells[0].expand
        assert cells[2].width == 150
        assert not cells[2].expand

    def test_row_widthless_column_expands(self) -> None:
        row = ExpandableTableRow(
            COLUMNS,
            ExpandableRow(cells=VALUES, expanded_content=ft.Text("detail")),
            is_expanded=False,
            on_toggle=lambda _e: None,
        )
        cells = _expandable_row_cells(row)
        assert cells[1].width is None
        assert cells[1].expand


def _hover(row: DataTableRow, entering: bool) -> None:
    """Drive the row's hover handler the way Flet does."""
    event = ft.ControlEvent(
        target="",
        name="hover",
        data="true" if entering else "false",
        control=row,
        page=None,
    )
    row._on_hover(event)


class TestHoverRevealedCells:
    """Row actions that only appear under the pointer.

    A table where every row shows its buttons reads as a wall of controls.
    Revealing them on hover keeps the data legible, but only if the row does
    not change size as the pointer crosses it.
    """

    def _row_with_action(self) -> tuple[DataTableRow, ft.Container]:
        action = ft.Container(content=ft.Text("Load"))
        action.reveal_on_hover = True
        row = DataTableRow(COLUMNS, ["6643", "FID FRDM 2040", action])
        return row, action

    def test_a_marked_action_starts_hidden(self) -> None:
        _, action = self._row_with_action()

        assert action.opacity == 0

    def test_hovering_reveals_it(self) -> None:
        row, action = self._row_with_action()

        _hover(row, True)

        assert action.opacity == 1
        assert action.disabled is False

    def test_leaving_hides_it_again(self) -> None:
        row, action = self._row_with_action()
        _hover(row, True)

        _hover(row, False)

        assert action.opacity == 0

    def test_a_hidden_action_cannot_be_clicked(self) -> None:
        """Invisible but still live would let the pointer trip an action the
        user cannot see."""
        _, action = self._row_with_action()

        assert action.disabled is True

    def test_the_cell_keeps_its_space_while_hidden(self) -> None:
        """Collapsing the control would change the row height as the pointer
        moves down the table, which reads as the whole table twitching."""
        _, action = self._row_with_action()

        assert action.visible is not False

    def test_an_unmarked_control_is_left_alone(self) -> None:
        plain = ft.Container(content=ft.Text("Always"))
        row = DataTableRow(COLUMNS, ["6643", "FID FRDM 2040", plain])

        _hover(row, True)
        _hover(row, False)

        assert plain.opacity is None or plain.opacity == 1
        assert plain.disabled is not True

    def test_an_action_can_opt_back_in_to_staying_visible(self) -> None:
        """An action in flight (a spinner mid-load) clears its own flag so it
        does not vanish when the pointer wanders off."""
        row, action = self._row_with_action()
        _hover(row, True)

        action.reveal_on_hover = False
        _hover(row, False)

        assert action.opacity == 1


def _rendered_first_cells(table: DataTable) -> list[str]:
    """First-column text of each rendered row, in display order."""
    body = table.content.controls[1]
    texts = []
    for row in body.controls:
        cell = row.content.controls[0]
        texts.append(cell.content.value)
    return texts


class TestSortableColumns:
    """Clicking a header sorts client-side; everything index-based follows."""

    def _table(self, **kwargs) -> DataTable:
        columns = [
            DataTableColumn("Name", width=100),
            DataTableColumn("Amount", width=80, alignment="right"),
        ]
        rows = [
            ["banana", "$1,200.00"],
            ["apple", "$90.00"],
            ["cherry", "—"],
        ]
        return DataTable(columns=columns, rows=rows, **kwargs)

    def test_click_sorts_ascending_then_descending(self) -> None:
        table = self._table()
        table._on_sort(0)
        assert _rendered_first_cells(table) == ["apple", "banana", "cherry"]
        table._on_sort(0)
        assert _rendered_first_cells(table) == ["cherry", "banana", "apple"]

    def test_money_sorts_numerically_with_blanks_last(self) -> None:
        table = self._table()
        table._on_sort(1)
        # $90 before $1,200 (numeric, not lexicographic); the dash sorts last.
        assert _rendered_first_cells(table) == ["apple", "banana", "cherry"]
        # Descending flips the values but the blank still loses.
        table._on_sort(1)
        assert _rendered_first_cells(table) == ["banana", "apple", "cherry"]

    def test_row_click_reports_the_original_index_after_sorting(self) -> None:
        clicked: list[int] = []
        table = self._table(on_row_click=clicked.append)
        table._on_sort(0)  # display order: apple(1), banana(0), cherry(2)
        body = table.content.controls[1]
        body.controls[0].on_click(None)  # topmost displayed row
        assert clicked == [1]  # "apple" was original row 1

    def test_pinned_last_rows_stay_at_the_bottom(self) -> None:
        columns = [DataTableColumn("Name", width=100)]
        rows = [["banana"], ["apple"], ["Total"]]
        table = DataTable(columns=columns, rows=rows, pinned_last_rows=1)
        table._on_sort(0)
        assert _rendered_first_cells(table) == ["apple", "banana", "Total"]

    def test_column_picker_hides_and_shows_columns(self) -> None:
        columns = [
            DataTableColumn("Name", width=100, hideable=False),
            DataTableColumn("Amount", width=80),
            DataTableColumn("Account", width=80, visible=False),
        ]
        rows = [["a", "$1.00", "Checking"]]
        table = DataTable(columns=columns, rows=rows, column_picker=True)
        # ships with Account hidden: Name + Amount cells + picker gutter
        body = table.content.controls[1]
        assert len(body.controls[0].content.controls) == 3
        table._toggle_column(2)
        assert len(table.content.controls[1].controls[0].content.controls) == 4
        # non-hideable Name is not offered in the menu
        menu = table._picker_cell().content
        assert [item.text for item in menu.items] == ["Amount", "Account"]

    def test_column_picker_guards_last_column_and_clears_hidden_sort(self) -> None:
        columns = [
            DataTableColumn("Name", width=100),
            DataTableColumn("Amount", width=80),
        ]
        table = DataTable(
            columns=columns,
            rows=[["b", "$2.00"], ["a", "$1.00"]],
            column_picker=True,
            initial_sort=1,
        )
        table._toggle_column(1)  # hide the active sort column
        assert table._sort_column is None
        assert _rendered_first_cells(table) == ["b", "a"]  # natural order back
        table._toggle_column(0)  # only column left: refuses to hide
        assert table._col_visible[0] is True

    def test_initial_sort_orders_rows_on_first_render(self) -> None:
        table = self._table(initial_sort=0)
        assert _rendered_first_cells(table) == ["apple", "banana", "cherry"]
        # Re-clicking the initial column flips to descending, as usual.
        table._on_sort(0)
        assert _rendered_first_cells(table) == ["cherry", "banana", "apple"]

    def test_initial_sort_descending_and_bogus_index_ignored(self) -> None:
        table = self._table(initial_sort=0, initial_sort_desc=True)
        assert _rendered_first_cells(table) == ["cherry", "banana", "apple"]
        untouched = self._table(initial_sort=99)
        assert _rendered_first_cells(untouched) == ["banana", "apple", "cherry"]

    def test_unsortable_column_click_is_a_no_op(self) -> None:
        import flet as ft

        columns = [
            DataTableColumn("Name", width=100),
            DataTableColumn("Actions", width=80),
        ]
        rows = [
            ["b", ft.Row([])],
            ["a", ft.Row([])],
        ]
        table = DataTable(columns=columns, rows=rows)
        table._on_sort(1)  # no extractable keys: ignored
        assert _rendered_first_cells(table) == ["b", "a"]

    def test_control_cells_sort_by_their_text(self) -> None:
        from app.components.frontend.controls.table import TableNameText

        columns = [DataTableColumn("Name", width=100)]
        rows = [[TableNameText("zeta")], [TableNameText("alpha")]]
        table = DataTable(columns=columns, rows=rows)
        table._on_sort(0)
        assert _rendered_first_cells(table) == ["alpha", "zeta"]

    def test_explicit_data_key_outranks_the_displayed_text(self) -> None:
        """Humanized dates display one way and must sort another. "Aug 1,
        2026" collates BEFORE "Sep 21, 2025" alphabetically, so a date
        column that sorted on its own display text put next year's bills
        above last year's in both directions. ``.data`` carries the ISO
        string and has to win over ``.value`` for that to come out right.
        """
        from app.components.frontend.dashboard.modals.modal_sections import (
            date_cell,
        )

        dates = ["2025-09-21", "2026-08-15", "2019-07-02", ""]
        table = DataTable(
            columns=[DataTableColumn("Next due", width=120)],
            rows=[[date_cell(d)] for d in dates],
        )
        table._on_sort(0)
        assert _rendered_first_cells(table) == [
            "Jul 2, 2019",
            "Sep 21, 2025",
            "Aug 15, 2026",
            "",  # undated rows lose in both directions
        ]
        table._on_sort(0)
        assert _rendered_first_cells(table) == [
            "Aug 15, 2026",
            "Sep 21, 2025",
            "Jul 2, 2019",
            "",
        ]


class TestSortAffordance:
    """Sortability must be visible before the first click."""

    def _headers(self, table: DataTable) -> list[ft.Container]:
        return list(table.content.controls[0].content.controls)

    def _interactive(self, table: DataTable, index: int = 0) -> ft.Container:
        """The tight clickable label+glyph container inside a header cell."""
        return self._headers(table)[index].content

    def test_sortable_headers_carry_the_faint_sort_glyph(self) -> None:
        table = DataTable(
            columns=[DataTableColumn("Name", width=100)], rows=[["a"], ["b"]]
        )
        interactive = self._interactive(table)
        assert interactive.content.controls[1].name == ft.Icons.UNFOLD_MORE
        assert interactive.on_click is not None

    def test_hover_target_hugs_the_label_not_the_cell(self) -> None:
        """An expanding column's cell can span half the table; the click
        target must be the label, not a mystery bar that wide."""
        table = DataTable(
            columns=[DataTableColumn("Payee")],  # width-less -> expands
            rows=[["a"], ["b"]],
        )
        cell = self._headers(table)[0]
        assert cell.expand  # the CELL still fills the column...
        interactive = cell.content
        assert interactive.on_click is not None  # ...but the BUTTON is inside
        assert getattr(interactive, "expand", None) in (None, False)
        row = interactive.content
        assert isinstance(row, ft.Row) and row.tight

    def test_active_column_shows_a_directional_arrow(self) -> None:
        table = DataTable(
            columns=[DataTableColumn("Name", width=100)], rows=[["a"], ["b"]]
        )
        table._on_sort(0)
        icon = self._interactive(table).content.controls[1]
        assert icon.name == ft.Icons.ARROW_DROP_UP
        table._on_sort(0)
        icon = self._interactive(table).content.controls[1]
        assert icon.name == ft.Icons.ARROW_DROP_DOWN

    def test_button_columns_get_no_glyph_and_no_click(self) -> None:
        table = DataTable(
            columns=[DataTableColumn("Actions", width=100)],
            rows=[[ft.Row([])], [ft.Row([])]],
        )
        header = self._headers(table)[0]
        assert header.on_click is None
        assert not isinstance(header.content, ft.Container)  # bare label


class TestPerRowSelectability:
    """A row that cannot participate in selection must not offer a
    checkbox.

    All Accounts interleaves trades with transactions, and the bulk
    actions apply only to transactions. The old shape gave every row a
    checkbox and silently ignored checked trades - and because trades
    sorted to the TOP of the register (newest trade beat the newest
    transaction by three days), ticking the first rows did nothing at
    all: no buttons, no feedback, reads as broken.
    """

    def _table(self, selectable_flags: list[bool]) -> DataTable:
        return DataTable(
            columns=[DataTableColumn("Name", width=100)],
            rows=[[f"row{i}"] for i in range(len(selectable_flags))],
            selectable=True,
            row_selectable=lambda i, flags=selectable_flags: flags[i],
        )

    def test_an_unselectable_row_gets_no_checkbox(self) -> None:
        table = self._table([True, False, True])
        body = table.content.controls[1]
        boxes = [
            row.content.controls[0].content.__class__.__name__
            if hasattr(row.content.controls[0], "content")
            else row.content.controls[0].__class__.__name__
            for row in body.controls
        ]
        assert boxes[0] == "SelectionCheckbox"
        assert boxes[1] != "SelectionCheckbox"
        assert boxes[2] == "SelectionCheckbox"

    def test_select_all_only_takes_the_selectable(self) -> None:
        seen: list[set[int]] = []
        table = DataTable(
            columns=[DataTableColumn("Name", width=100)],
            rows=[["a"], ["b"], ["c"]],
            selectable=True,
            row_selectable=lambda i: i != 1,
            on_selection_change=seen.append,
        )
        table._toggle_all(True)
        assert seen[-1] == {0, 2}

    def test_header_checkbox_fills_from_the_selectable_count(self) -> None:
        """Two of three rows selectable: selecting both must read as
        'all selected', not stuck at two-thirds forever."""
        table = self._table([True, False, True])
        table._toggle_row(0, True)
        table._toggle_row(2, True)
        header = table._selection_header_cell()
        assert header.content.value is True

    def test_without_the_predicate_every_row_selects(self) -> None:
        seen: list[set[int]] = []
        table = DataTable(
            columns=[DataTableColumn("Name", width=100)],
            rows=[["a"], ["b"]],
            selectable=True,
            on_selection_change=seen.append,
        )
        table._toggle_all(True)
        assert seen[-1] == {0, 1}
