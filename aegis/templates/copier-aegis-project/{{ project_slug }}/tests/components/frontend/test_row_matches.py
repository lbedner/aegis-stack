"""Client-side search, shared by the tabs that hold their whole dataset.

Bills & Income and Payees fetch everything (330 streams, 47 payees), so
they filter in memory. Both matched the NAME only while showing five or
six columns, so searching a category or an account came back empty and
read as "no such bill".

The register is deliberately NOT on this path: it pages at 100 rows of a
5,552-row account, so filtering what happens to be loaded would silently
miss the rest. That one searches server-side.
"""

from app.components.frontend.dashboard.modals.modal_sections import row_matches


class TestRowMatches:
    def test_an_empty_query_matches_everything(self) -> None:
        assert row_matches("", ["anything"]) is True

    def test_it_searches_every_value_given(self) -> None:
        row = ["Stop & Shop", "Food & Dining:Groceries", "TOTAL CHECKING (CHASE)"]
        assert row_matches("groceries", row) is True
        assert row_matches("chase", row) is True
        assert row_matches("stop", row) is True

    def test_it_is_case_insensitive(self) -> None:
        assert row_matches("ChAsE", ["TOTAL CHECKING (CHASE)"]) is True

    def test_no_match_is_false(self) -> None:
        assert row_matches("zzz", ["Stop & Shop", "Groceries"]) is False

    def test_none_and_numbers_do_not_blow_up(self) -> None:
        """Rows carry None for an unset category and ints for cents."""
        assert row_matches("500", [None, 500, "x"]) is True
        assert row_matches("x", [None, 500, "x"]) is True

    def test_whitespace_only_is_treated_as_empty(self) -> None:
        assert row_matches("   ", ["anything"]) is True
