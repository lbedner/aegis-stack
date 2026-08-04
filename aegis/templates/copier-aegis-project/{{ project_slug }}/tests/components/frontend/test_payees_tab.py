"""Tests for the Payees tab's own state.

The drill-down holds the payee it opened on so its header can name it.
That copy is taken once, which is fine until an edit lands: the list
behind it reloads, the header does not, and the thing you just renamed
still shows its old name (and its old icon) directly above the table.
"""

from app.components.frontend.dashboard.modals.finance_payees_tab import PayeesTab


def _tab(items: list[dict], open_payee: dict | None) -> PayeesTab:
    """A PayeesTab with just the state under test - constructing one for
    real needs a live ft.Page."""
    tab = object.__new__(PayeesTab)
    tab._items = items
    tab._open_payee = open_payee
    return tab


class TestOpenPayeeStaysCurrent:
    def test_an_edit_updates_the_open_header(self) -> None:
        tab = _tab(
            items=[
                {"id": 7, "name": "Citizens Bank", "website_url": "citizensbank.com"}
            ],
            open_payee={"id": 7, "name": "Citizens", "website_url": None},
        )

        tab._refresh_open_payee()

        assert tab._open_payee is not None
        assert tab._open_payee["name"] == "Citizens Bank"
        assert tab._open_payee["website_url"] == "citizensbank.com"

    def test_the_directory_view_is_untouched(self) -> None:
        tab = _tab(items=[{"id": 7, "name": "Citizens"}], open_payee=None)

        tab._refresh_open_payee()

        assert tab._open_payee is None

    def test_a_payee_that_vanished_closes_the_drilldown(self) -> None:
        """Rather than stranding a header over a table of rows whose payee
        no longer exists."""
        tab = _tab(
            items=[{"id": 9, "name": "Other"}],
            open_payee={"id": 7, "name": "Gone"},
        )

        tab._refresh_open_payee()

        assert tab._open_payee is None
