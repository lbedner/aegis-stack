"""The register header's layout contract.

Its title/subtitle Column is the only flexible child of a Row otherwise
full of fixed-width controls (seven range chips, a 280px search box). Flex
gets what is LEFT, so every fixed control added to that Row comes out of
the title's width - and past the limit it collapses to a few pixels and
wraps one character per line down the page. Confirmed live once three
bulk-action chips were added to it.

So the rule this pins: selection controls belong on their own row, and
the title text can never wrap even if the rule is broken again.
"""

import inspect

from app.components.frontend.dashboard.modals import finance_modal


class TestHeaderLayout:
    def _source(self) -> str:
        return inspect.getsource(finance_modal.TransactionsPanel)

    def test_bulk_actions_are_not_in_the_title_row(self) -> None:
        source = self._source()
        header = source[source.index("self.content = ft.Column(") :]
        header_row = header[: header.index("self._selection_row,")]
        for control in (
            "_bulk_payee_trigger",
            "_bulk_categorize_trigger",
            "_bulk_recurring_trigger",
            "_selection_label",
        ):
            assert control not in header_row, f"{control} is back in the title row"

    def test_the_selection_row_starts_hidden(self) -> None:
        """It must claim no height with nothing selected, or the table
        sits behind a permanent blank strip."""
        source = self._source()
        row = source[source.index("self._selection_row = ft.Container(") :]
        assert "visible=False," in row[: row.index("self.content")]

    def test_the_selection_row_follows_the_selection(self) -> None:
        source = self._source()
        assert "self._selection_row.visible = bool(count or trades)" in source

    def test_title_and_subtitle_cannot_wrap(self) -> None:
        source = self._source()
        assert source.count("no_wrap=True") >= 2
        assert source.count("overflow=ft.TextOverflow.ELLIPSIS") >= 2

    def test_the_selection_row_repaints_even_when_unmounted(self) -> None:
        """A control that has never been visible may have no ``.page``, so
        the guarded ``self._selection_row.update()`` is skipped and the
        bulk buttons never appear however many rows are checked. Reported
        live with a payee filter active. There has to be a fallback to a
        parent that IS mounted.
        """
        source = self._source()
        block = source[source.index("self._selection_row.visible = bool(count or trades)") :]
        block = block[: block.index("def ")]
        assert "elif self.page is not None:" in block
        assert "self.update()" in block


class TestRecurringTabPickerMount:
    """A control referenced in a class's own tree has to be defined by
    that class.

    ``self._category_picker`` was spliced into BOTH panels in this module
    by an unbounded string replace - ProjectionPanel never defines it, so
    the Projected tab raised AttributeError at construction and the tab
    would not render at all. Nothing catches that until the page is
    opened, so it is asserted here.
    """

    def test_each_panel_mounts_only_what_it_defines(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_recurring_tab

        for name in ("ProjectionPanel", "RecurringTab"):
            source = inspect.getsource(getattr(finance_recurring_tab, name))
            defines = "_category_picker = CategoryPickerButton" in source
            mounts = "_category_picker," in source
            assert defines == mounts, f"{name}: defines={defines} mounts={mounts}"


class TestMixedSelectionNarratesItself:
    """Trades select like anything else - and the label says what they
    can and cannot do.

    ``FinanceTrade`` carries no payee or category columns, so the bulk
    actions structurally cannot apply to a trade. Two failed shapes came
    before this one: silently dropping checked trades (ticking the top
    rows of All Accounts produced no buttons and no feedback - the newest
    trade postdates the newest transaction, so trades sort first), then
    removing their checkboxes entirely (the user needs to select them).
    The rule now: everything selects, actions arm on the transactions in
    the selection, and the label narrates the split.
    """

    def _panel(self):
        from unittest.mock import MagicMock

        import flet as ft

        from app.components.frontend.dashboard.modals.finance_modal import (
            TransactionsPanel,
        )

        return TransactionsPanel(MagicMock(spec=ft.Page))

    def test_a_mixed_selection_counts_both(self) -> None:
        panel = self._panel()
        panel._selected_txn_ids = {1, 2, 3}
        panel._selected_amount = -5_000
        panel._selected_trade_count = 2
        panel._update_selection_label()
        assert "3 selected" in panel._selection_label.value
        assert "2 trades" in panel._selection_label.value
        assert panel._bulk_payee_trigger.visible is True

    def test_trades_only_explains_why_no_actions(self) -> None:
        panel = self._panel()
        panel._selected_txn_ids = set()
        panel._selected_trade_count = 2
        panel._update_selection_label()
        assert panel._selection_row.visible is True
        assert "no payee or category" in panel._selection_label.value
        assert panel._bulk_payee_trigger.visible is False

    def test_the_register_no_longer_strips_trade_checkboxes(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.TransactionsPanel)
        assert "row_selectable" not in source
