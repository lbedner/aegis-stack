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
        assert headers == ["Date", "Account", "Payee", "Category", "Source", "Amount"]

    def test_a_single_account_does_not(self) -> None:
        headers = [c.header for c in register_columns(False)]
        assert "Account" not in headers
        assert headers == ["Date", "Payee", "Category", "Source", "Amount"]

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
