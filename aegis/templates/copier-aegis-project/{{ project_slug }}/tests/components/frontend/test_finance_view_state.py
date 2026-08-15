"""The finance view state survives the things that recreate the dialog.

The account filter caused a real scare: a projection read one way under
a narrowed filter, the session restarted (page reload; every hot-reload
in dev), the filter silently reset to All accounts, and the same screen
told a different story. The dialog and ``SessionState`` both die with
the Flet page, so neither can hold it.

So view state lives in a process-level store, keyed per owner, handing
out the SAME mutable objects every time - a recreated dialog gets the
filter it had, not a fresh one. In memory on purpose: it survives page
reloads for as long as the server runs, and persisting it further is a
later decision, not this one.
"""

from app.components.frontend.dashboard.modals.finance_modal import AccountFilter
from app.components.frontend.state.finance_view_state import (
    FinanceViewState,
    finance_view_state,
    reset_finance_view_state,
)


class TestTheStore:
    def setup_method(self) -> None:
        reset_finance_view_state()

    def test_the_same_owner_gets_the_same_state_back(self) -> None:
        """The property that makes a narrowed filter survive a page
        reload: identity, not equality."""
        first = finance_view_state(owner_key="solo")
        again = finance_view_state(owner_key="solo")
        assert first is again
        assert first.account_filter is again.account_filter

    def test_a_narrowed_filter_survives_dialog_recreation(self) -> None:
        """What actually happened, as a test: narrow the filter, lose the
        dialog, get a new one - the narrowing must still be there."""
        finance_view_state(owner_key="solo").account_filter.selected = {45, 46}

        rebuilt = finance_view_state(owner_key="solo")

        assert rebuilt.account_filter.selected == {45, 46}

    def test_owners_do_not_share_state(self) -> None:
        """An auth stack has several users on one server process; one
        user's narrowed view must never become another's."""
        finance_view_state(owner_key="7").account_filter.selected = {1}

        other = finance_view_state(owner_key="8")

        assert other.account_filter.selected is None

    def test_the_state_is_a_real_account_filter(self) -> None:
        """The store hands out the SAME type the dialog already uses -
        one filter implementation, not a parallel one to keep in sync."""
        assert isinstance(
            finance_view_state(owner_key="solo").account_filter, AccountFilter
        )

    def test_reset_clears_everything(self) -> None:
        finance_view_state(owner_key="solo").account_filter.selected = {1}
        reset_finance_view_state()
        assert finance_view_state(owner_key="solo").account_filter.selected is None

    def test_the_state_object_is_extensible(self) -> None:
        """The point of a dataclass over a bare filter: the next piece of
        view state (a range chip, a tab) is a field here, not a second
        store."""
        assert isinstance(finance_view_state(owner_key="solo"), FinanceViewState)


class TestTheDialogUsesIt:
    def test_the_dialog_pulls_its_filter_from_the_store(self) -> None:
        """Pinned structurally, like the global-filter tests above: a
        dialog that constructs ``AccountFilter()`` privately has state
        that dies with it."""
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.FinanceDetailDialog.__init__)
        assert "finance_view_state(" in source
        assert "self._account_filter = AccountFilter()" not in source
