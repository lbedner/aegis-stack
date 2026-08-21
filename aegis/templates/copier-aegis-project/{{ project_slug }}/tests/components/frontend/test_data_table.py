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
    body = table.content.controls[1].content
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
        body = table.content.controls[1].content
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
        body = table.content.controls[1].content
        assert len(body.controls[0].content.controls) == 3
        table._toggle_column(2)
        assert len(table.content.controls[1].content.controls[0].content.controls) == 4
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
        # .content twice: the skeleton's header HOST, then the header.
        return list(table.content.controls[0].content.content.controls)

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
        body = table.content.controls[1].content
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


class TestTheTableKeepsItsScrollContainer:
    """New data mutates the mounted ListView; it never replaces it.

    Scroll position lives in the Flutter element behind the ListView, so
    the ONLY way to keep it is to keep the instance. Every edit in the
    register used to build a brand-new DataTable (and every sort built a
    new ListView inside this one), which is why any update snapped the
    view back to the top. ``_toggle_expand`` already mutates in place for
    exactly this reason - these tests make that the rule, not the
    exception.
    """

    def _table(self, rows=None, **kwargs):
        return DataTable(
            columns=COLUMNS,
            rows=rows if rows is not None else [VALUES, ["A", "B", "$2.00"]],
            expand=True,
            **kwargs,
        )

    def test_set_rows_keeps_the_same_listview(self) -> None:
        table = self._table()
        lv = table._data_content
        assert isinstance(lv, ft.ListView)

        table.set_rows([["X", "Y", "$9.00"]])

        assert table._data_content is lv
        assert len(lv.controls) == 1

    def test_a_resort_keeps_the_same_listview(self) -> None:
        table = self._table()
        lv = table._data_content

        table._on_sort(0)

        assert table._data_content is lv

    def test_a_column_toggle_keeps_the_same_listview(self) -> None:
        table = self._table(column_picker=True)
        lv = table._data_content

        table._toggle_column(1)

        assert table._data_content is lv

    def test_the_root_content_is_never_replaced(self) -> None:
        """The ListView surviving is not enough on its own: replacing any
        ancestor remounts the subtree and Flutter forgets the offset. The
        skeleton is built once and only its hosts' contents change."""
        table = self._table()
        root = table.content

        table.set_rows([["X", "Y", "$9.00"]])
        table._on_sort(0)

        assert table.content is root

    def test_sort_choice_survives_new_data(self) -> None:
        """The user sorted by a column; an edit refreshing the rows must
        not silently unsort the table."""
        table = self._table(rows=[["b", "x", "$1.00"], ["a", "y", "$2.00"]])
        table._on_sort(0)  # ascending by first column

        table.set_rows([["d", "x", "$1.00"], ["c", "y", "$2.00"]])

        first_cell = _cells(table._data_content.controls[0])[0]
        text = first_cell.content
        assert getattr(text, "value", None) == "c"

    def test_empty_and_back_recovers(self) -> None:
        table = self._table()
        table.set_rows([])
        # placeholder shown, no crash
        assert not isinstance(table._data_content, ft.ListView)

        table.set_rows([VALUES])

        assert isinstance(table._data_content, ft.ListView)
        assert len(table._data_content.controls) == 1

    def test_set_rows_clears_selection_by_default(self) -> None:
        table = self._table(selectable=True)
        table._selected = {0}

        table.set_rows([["X", "Y", "$9.00"]])

        assert table._selected == set()

    def test_set_rows_can_seed_a_carried_selection(self) -> None:
        table = self._table(selectable=True)

        table.set_rows([VALUES, ["A", "B", "$2.00"]], selected_indices={1})

        assert table._selected == {1}

    def test_set_rows_can_swap_the_expand_builder(self) -> None:
        """The register's expand pane closes over the fetched rows, so a
        data refresh must be able to hand the table the new closure - and
        stale expand panels must not survive into the new data."""
        table = self._table(expandable_content=lambda i: ft.Text("old"))
        table._expand_cache[0] = ft.Text("cached")
        table._expanded.add(0)

        new_builder = lambda i: ft.Text("new")  # noqa: E731
        table.set_rows([VALUES], expandable_content=new_builder)

        assert table._expandable_content is new_builder
        assert table._expand_cache == {}
        assert table._expanded == set()


class TestExpandNeverChangesScrollMode:
    """An expandable table must never flip the ListView's item_extent.

    The flip (fixed extent while collapsed, none while a panel is open)
    swaps Flutter's sliver type, and at scroll depth the swap re-anchors
    the viewport ~ten rows off. Correcting it with scroll_to was worse:
    ensure-visible aligns EVERY ancestor scrollable, so the whole tab
    jerked horizontally (confirmed live, both). The fix removes the
    cause: expandable tables carry the fixed height on each ROW and the
    ListView stays in one sliver mode for its whole life. Tables without
    expandable rows keep the true item_extent fast path - they can never
    flip.
    """

    def _table(self, expandable=True):
        return DataTable(
            columns=COLUMNS,
            rows=[[f"r{i}", "x", "$1.00"] for i in range(6)],
            expand=True,
            item_extent=40,
            expandable_content=(lambda i: ft.Text("detail")) if expandable else None,
        )

    def test_an_expandable_table_never_sets_a_sliver_extent(self) -> None:
        table = self._table()
        assert table._data_content.item_extent is None

    def test_its_rows_carry_the_fixed_height_instead(self) -> None:
        table = self._table()
        assert all(c.height == 40 for c in table._data_content.controls)

    def test_expanding_and_collapsing_leave_the_mode_alone(self) -> None:
        table = self._table()
        table._toggle_expand(2)
        assert table._data_content.item_extent is None
        table._toggle_expand(2)
        assert table._data_content.item_extent is None

    def test_the_panel_itself_is_not_height_capped(self) -> None:
        """The whole reason the extent could not stay on the sliver: the
        expansion panel is taller than a row and must not be clipped."""
        table = self._table()
        table._toggle_expand(2)
        panel = table._expand_widgets[2]
        assert panel.height is None

    def test_a_plain_table_keeps_the_analytic_fast_path(self) -> None:
        table = self._table(expandable=False)
        assert table._data_content.item_extent == 40


class TestOneHoverAtATime:
    """The hover tint self-heals instead of trusting exit events.

    The tint is Python state cleared by pointer-EXIT - but a virtualized
    row that scrolls out from under the pointer unmounts before its exit
    event fires, so the tint sticks and rides back in with the row
    (confirmed live: four rows wearing it at once). The table now owns
    the invariant: entering any row clears the previous holder.
    """

    def _table(self):
        return DataTable(
            columns=COLUMNS,
            rows=[[f"r{i}", "x", "$1.00"] for i in range(4)],
            expand=True,
        )

    def _hover(self, row, hovered):
        from types import SimpleNamespace

        row._on_hover(SimpleNamespace(control=row, data="true" if hovered else "false"))

    def test_entering_a_row_clears_the_stuck_one(self) -> None:
        table = self._table()
        first, second = table._data_content.controls[0], table._data_content.controls[1]

        self._hover(first, True)  # ...and the exit event never arrives
        tinted = first.bgcolor
        self._hover(second, True)

        assert first.bgcolor == first._default_bgcolor
        assert second.bgcolor == tinted

    def test_a_normal_exit_still_works(self) -> None:
        table = self._table()
        first = table._data_content.controls[0]

        self._hover(first, True)
        self._hover(first, False)

        assert first.bgcolor == first._default_bgcolor

    def test_new_data_forgets_the_hovered_row(self) -> None:
        """set_rows swaps every row control; holding a reference to a
        dead one must not clear tints on rows no longer shown."""
        table = self._table()
        self._hover(table._data_content.controls[0], True)

        table.set_rows([["X", "x", "$1.00"]])

        assert table._hovered_row is None
