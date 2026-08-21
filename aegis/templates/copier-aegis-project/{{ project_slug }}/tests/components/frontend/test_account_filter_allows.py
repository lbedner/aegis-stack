"""What an account filter does with a row that has no account.

A bill or income typed in by hand (Add, or Make recurring without a
ledger) has ``account_id = None``. Filtering it against a set of chosen
accounts asks "is None one of them", which is always False - so narrowing
the view to any account made every hand-entered row vanish everywhere.

Confirmed live: "Betr Health" saved correctly (inflow, semi_monthly,
$5,000, confirmed) and showed up on no tab at all.
"""

from app.components.frontend.dashboard.modals.finance_modal import AccountFilter


class TestAllows:
    def test_no_selection_allows_everything(self) -> None:
        f = AccountFilter()
        assert f.allows(1) is True
        assert f.allows(None) is True

    def test_a_selection_narrows_to_those_accounts(self) -> None:
        f = AccountFilter()
        f.selected = {1, 2}
        assert f.allows(1) is True
        assert f.allows(3) is False

    def test_a_row_with_no_account_is_never_filtered_out(self) -> None:
        """It belongs to no account, so no account selection excludes it.
        The alternative - hiding it - loses data the user typed in and
        cannot get back by changing tabs."""
        f = AccountFilter()
        f.selected = {1, 2}
        assert f.allows(None) is True

    def test_even_an_empty_selection_keeps_it(self) -> None:
        f = AccountFilter()
        f.selected = set()
        assert f.allows(None) is True
