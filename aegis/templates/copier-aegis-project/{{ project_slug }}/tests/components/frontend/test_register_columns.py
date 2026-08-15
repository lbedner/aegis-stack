"""The register's column set, and its one conditional column.

Account is shown only in All Accounts. The column and the cell that fills
it are gated on the same flag, so this pins the count: a mismatch between
them does not error, it silently shifts every cell one column left, and
the table reads plausibly wrong (a date under Account, a payee under
Category) rather than obviously broken.
"""

import inspect
import re

from app.components.frontend.dashboard.modals import finance_modal
from app.components.frontend.dashboard.modals.finance_modal import register_columns


class TestRegisterColumns:
    def test_all_accounts_gets_an_account_column(self) -> None:
        headers = [c.header for c in register_columns(True)]
        assert headers == [
            "Date",
            "Account",
            "Payee",
            "Category",
            "Tags",
            "Source",
            "Amount",
        ]

    def test_a_single_account_does_not(self) -> None:
        headers = [c.header for c in register_columns(False)]
        assert "Account" not in headers
        assert headers == ["Date", "Payee", "Category", "Tags", "Source", "Amount"]

    def test_exactly_one_column_differs_between_the_two(self) -> None:
        assert len(register_columns(True)) == len(register_columns(False)) + 1

    def test_the_account_column_sits_second(self) -> None:
        """Right after Date, matching every other table that shows it
        (No payee, the payee drill-down, the recurring preview)."""
        assert register_columns(True)[1].header == "Account"

    def test_both_row_shapes_fill_the_conditional_cell(self) -> None:
        """Transactions AND trades merge into one table in All Accounts,
        so a trade row missing the Account cell would misalign only the
        trade rows - the kind of gap that survives a glance at the top of
        the table."""
        source = inspect.getsource(finance_modal.TransactionsPanel)
        # The trade branch and the transaction branch must each splice it.
        assert len(re.findall(r"\*_account_cell\(record\)", source)) == 2

    def test_the_cell_is_empty_when_the_column_is_absent(self) -> None:
        """The gate lives in one place: _account_cell returns [] rather
        than each call site re-checking the flag."""
        source = inspect.getsource(finance_modal.TransactionsPanel)
        assert "if not all_accounts:\n                return []" in source


class TestExcludedRowsRecede:
    """A row flagged out of reports must LOOK inert where the eye scans:
    the amount. No new element (a dot would collide with status-dot
    semantics elsewhere) - the money color is simply taken away, which
    in a monochrome-first system is itself the statement.
    """

    def test_a_normal_inflow_keeps_its_teal(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            _amount_cell,
            ledger_amount_color,
        )

        cell = _amount_cell(23_171)
        assert cell.color == ledger_amount_color(23_171)

    def test_an_excluded_amount_is_muted_ink(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import _amount_cell
        from app.components.frontend.theme import AegisTheme as Theme

        for cents in (23_171, -23_171):
            cell = _amount_cell(cents, excluded=True)
            assert cell.color == Theme.Colors.TEXT_SECONDARY

    def test_the_table_wires_the_flag_through(self) -> None:
        """An excluded inflow in a real table renders muted while its
        neighbour keeps the money color."""
        import flet as ft

        from app.components.frontend.dashboard.modals.finance_modal import (
            ledger_amount_color,
            transaction_table,
        )
        from app.components.frontend.theme import AegisTheme as Theme

        table = transaction_table(
            [
                {"date": "2026-07-17", "name": "Adj Redist Bal", "amount": 23_171,
                 "excluded_from_reports": True},
                {"date": "2026-07-17", "name": "Paycheck", "amount": 23_171,
                 "excluded_from_reports": False},
            ]
        )

        def walk(c):
            yield c
            if getattr(c, "content", None) is not None:
                yield from walk(c.content)
            for item in getattr(c, "controls", None) or []:
                yield from walk(item)

        amounts = [
            c for c in walk(table)
            if isinstance(c, ft.Text) and c.value == "$231.71"
        ]
        assert len(amounts) == 2
        colors = {c.color for c in amounts}
        assert Theme.Colors.TEXT_SECONDARY in colors
        assert ledger_amount_color(23_171) in colors


class TestTheRegisterAdmitsItsPageEdge:
    """The register caps what one fetch returns, and the subtitle used to
    claim "685 transactions" while the newest 100 rendered - rows past
    the edge read as data loss (confirmed live: a mid-July pair "just
    not there at all"). The COUNT LINE now states the truth, and the
    Load-more affordance rides beside it in chrome that already existed:
    a bottom footer was tried first and permanently cost the table a
    row's height in a modal with none to spare.
    """

    def _label(self, shown, total, **kw):
        from app.components.frontend.dashboard.modals.finance_modal import (
            register_count_label,
        )

        return register_count_label(shown, total, **kw)

    def test_a_truncated_page_says_shown_of_total(self) -> None:
        assert self._label(100, 685) == "Showing 100 of 685 transactions"

    def test_a_complete_page_keeps_the_plain_count(self) -> None:
        assert self._label(685, 685) == "685 transactions"
        assert self._label(None, 685) == "685 transactions"

    def test_one_transaction_is_singular(self) -> None:
        assert self._label(1, 1) == "1 transaction"

    def test_a_filtered_view_keeps_its_matching_noun(self) -> None:
        assert self._label(13, 40, noun="matching") == "Showing 13 of 40 matching"
        assert self._label(40, 40, noun="matching") == "40 matching"


class TestTheLanesStayLevel:
    """The register merges two lanes - paginated transactions, unpaginated
    trades - and must never render one deeper than the other reaches.

    All-accounts showed Chase rows down to the transaction page's edge,
    then a tail of nothing but IRA trades below it: it read as "Chase and
    AMEX just stop after a certain date" (confirmed live) when really the
    transaction PAGE had ended while every trade kept rendering past it.
    """

    def _within(self, trades, oldest, complete):
        from app.components.frontend.dashboard.modals.finance_modal import (
            trades_within_page,
        )

        return trades_within_page(trades, oldest_txn_date=oldest, page_complete=complete)

    def test_trades_past_the_page_edge_wait_for_load_more(self) -> None:
        trades = [
            {"trade_date": "2026-07-28", "name": "BUY"},
            {"trade_date": "2026-07-10", "name": "DIVIDEND"},
        ]
        kept = self._within(trades, "2026-07-27", False)
        assert [t["trade_date"] for t in kept] == ["2026-07-28"]

    def test_a_trade_on_the_edge_date_still_shows(self) -> None:
        trades = [{"trade_date": "2026-07-27", "name": "BUY"}]
        assert self._within(trades, "2026-07-27", False) == trades

    def test_a_complete_page_shows_every_trade(self) -> None:
        """When the transaction lane is fully fetched there is no deeper
        edge to respect."""
        trades = [{"trade_date": "2020-01-01", "name": "OLD BUY"}]
        assert self._within(trades, "2026-07-27", True) == trades

    def test_a_trades_only_stack_shows_its_trades(self) -> None:
        """No transactions at all (a brokerage-only install) must not
        hold every trade hostage to an edge that does not exist."""
        trades = [{"trade_date": "2020-01-01", "name": "OLD BUY"}]
        assert self._within(trades, None, True) == trades
