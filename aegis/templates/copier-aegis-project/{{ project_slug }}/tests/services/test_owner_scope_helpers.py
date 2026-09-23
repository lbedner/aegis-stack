"""The owner-scoping helpers every owned query shares.

Two meanings of a ``None`` owner coexist, and each helper names one:
``owner_filters`` treats it as "no filter" (a standalone install sees every
row), ``stored_owner`` as the ``0`` owner a NOT NULL column stores it under.

The module ships in every stack, including ones with no database, so the
column here is a stand-in that records the comparison rather than a
SQLAlchemy column.
"""

from typing import Any

from app.services.shared.queries import owner_filters, stored_owner


class _Column:
    def __eq__(self, other: object) -> Any:  # type: ignore[override]
        return ("owner ==", other)

    __hash__ = object.__hash__


def test_an_owner_scopes_to_that_owner() -> None:
    assert owner_filters(_Column(), 7) == [("owner ==", 7)]


def test_no_owner_filters_nothing() -> None:
    assert owner_filters(_Column(), None) == []


def test_no_owner_is_stored_as_zero() -> None:
    assert stored_owner(None) == 0


def test_an_owner_is_stored_as_itself() -> None:
    assert stored_owner(7) == 7
