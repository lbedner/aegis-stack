"""The owner-scoping helpers every owned query shares.

Two meanings of a ``None`` owner coexist, and each helper names one:
``owner_filters`` and ``visible_to`` treat it as "no filter" (a standalone
install sees every row), ``stored_owner`` as the ``0`` owner a NOT NULL
column stores it under.

The module ships in every stack, including ones with no database, so the
column here is a stand-in that records the comparison rather than a
SQLAlchemy column.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.shared.queries import (
    owner_filters,
    stored_owner,
    visible_to,
    within,
)


class _Clause:
    def __init__(self, text: Any) -> None:
        self.text = text

    def __or__(self, other: object) -> Any:
        return ("or", self.text, other)


class _Column:
    def __eq__(self, other: object) -> Any:  # type: ignore[override]
        return ("owner ==", other)

    __hash__ = object.__hash__

    def is_(self, other: object) -> _Clause:
        return _Clause(("owner is", other))


def test_an_owner_scopes_to_that_owner() -> None:
    assert owner_filters(_Column(), 7) == [("owner ==", 7)]


def test_no_owner_filters_nothing() -> None:
    assert owner_filters(_Column(), None) == []


def test_an_owner_sees_the_shared_rows_and_their_own() -> None:
    assert visible_to(_Column(), 7) == [("or", ("owner is", None), ("owner ==", 7))]


def test_no_owner_sees_everything() -> None:
    assert visible_to(_Column(), None) == []


def test_no_owner_is_stored_as_zero() -> None:
    assert stored_owner(None) == 0


def test_an_owner_is_stored_as_itself() -> None:
    assert stored_owner(7) == 7


class _Timestamp:
    def __ge__(self, other: object) -> Any:
        return (">=", other)

    def __lt__(self, other: object) -> Any:
        return ("<", other)


def test_a_window_is_bounded_on_the_columns_clock() -> None:
    """The timestamp columns store naive UTC, and Postgres refuses an aware
    bound against them: an aware window (an API's ``?start_time=...Z``) is
    compared as the same instant in naive UTC."""
    east = timezone(timedelta(hours=2))
    start = datetime(2026, 11, 9, 2, tzinfo=east)
    end = datetime(2026, 11, 10)

    assert within(_Timestamp(), start, end) == [
        (">=", datetime(2026, 11, 9, 0)),
        ("<", end),
    ]
