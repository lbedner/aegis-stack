"""What a filter on a table's rows may ask (Database > Tables > Rows), and
how it is carried in the URL. One rule, ``operators``, says which
comparisons a column's kind allows: the page offers only those (sent with
it, no request) and ``conditions`` keeps them for what arrives, a URL
edited by hand included. Never a column holding a secret, bytes or JSON
(``filterable``); a value read as its column's kind (``value``); filters
written as ``where_text`` and read back the same by ``parse_where``
(``ask`` refuses one that would not be)."""

from collections.abc import Callable, Collection, Sequence
import operator
import re
from typing import Any

from sqlalchemy import Boolean, Column, Table, TypeDecorator

TRUE = frozenset({"1", "true", "t", "yes", "on"})
FALSE = frozenset({"0", "false", "f", "no", "off"})
BIGGEST = 2**63  # past a 64-bit integer, the database refuses the value mid-read
# What a filter may ask of a column: its sign as written (``where``, the
# URL; ``:`` for equals, as the row links write it), as shown, and the
# comparison.
OPERATORS: dict[str, tuple[str, Callable[[Any, Any], Any]]] = {
    ":": ("=", operator.eq),
    # NULL is not the value either: SQL's ``!=`` would drop it unsaid.
    "!=": ("≠", lambda column, value: column.is_distinct_from(value)),
    "<": ("<", operator.lt),
    "<=": ("≤", operator.le),
    ">": (">", operator.gt),
    ">=": ("≥", operator.ge),
}
# Text and flags are only matched: a flag ordered means nothing, and text
# ordered would spell out, a character at a time, what the page hides
# (``redact``, the cut).
MATCHES = [":", "!="]
Filter = tuple[str, str, str]  # a column, one of ``OPERATORS``, a value
_SIGNS = "|".join(sorted(map(re.escape, OPERATORS), key=len, reverse=True))
_FILTER = re.compile(rf"\s*(\w+)\s*({_SIGNS})\s*(.*?)\s*")


class AskError(ValueError):
    """What was asked of a table's rows cannot be: a column it may not
    filter or order by, a comparison its kind does not allow
    (``operators``), a value not of its kind, a filter its text could not
    carry back (``ask``), a page too deep."""


def holds(column: Column[Any]) -> type | None:
    """The Python type a column holds, through a wrapping type (SQLModel's
    ``AutoString`` wraps ``String`` and says nothing of its own)."""
    kind = column.type
    if isinstance(kind, TypeDecorator):
        kind = kind.impl_instance
    try:
        return kind.python_type
    except NotImplementedError:
        return None


def textual(column: Column[Any]) -> bool:
    return holds(column) in (str, dict, list)


def operators(column: Column[Any]) -> list[str]:
    """The comparisons a column's kind allows (keys of ``OPERATORS``)."""
    if textual(column) or isinstance(column.type, Boolean):
        return MATCHES
    return list(OPERATORS)


def filterable(table: Table, hidden: Collection[str]) -> list[str]:
    """What a filter may compare, in the table's order: any column but a
    secret (``hidden``: its values told apart unshown), bytes (nothing to
    type) or JSON (no equality on PostgreSQL). One no index serves reads
    the table through, which the read's time limit stops."""
    return [
        c.name
        for c in table.columns
        if c.name not in hidden and holds(c) not in (bytes, dict, list)
    ]


def conditions(
    table: Table, filters: Sequence[Filter], allowed: Collection[str]
) -> list[Any]:
    """Each filter as the clause a query keeps rows by; AskError for one
    on a column not ``allowed`` (``filterable``), a comparison ``operators``
    does not allow, or a value not of its column's kind."""
    found = []
    for name, op, text in filters:
        if name not in allowed:
            raise AskError(f"{table.name} has no column {name!r} to filter by.")
        column = table.columns[name]
        if op not in operators(column):
            signs = " or ".join(OPERATORS[o][0] for o in MATCHES)
            raise AskError(f"{name} can be matched ({signs}), not ordered.")
        found.append(OPERATORS[op][1](column, value(column, text)))
    return found


def value(column: Column[Any], text: str) -> Any:
    """``text`` as the column's own type, for the database to compare (a date
    as the page shows it); AskError where it is not one."""
    if isinstance(column.type, Boolean):
        if text.lower() not in TRUE | FALSE:
            raise AskError(f"{column.name} is true or false: {text!r} is neither.")
        return text.lower() in TRUE
    kind = holds(column)
    if kind is None or kind is str:
        return text
    try:
        found = getattr(kind, "fromisoformat", kind)(text)  # a date: as shown
        if kind is int and not -BIGGEST <= found < BIGGEST:
            raise ValueError(text)
    except (ArithmeticError, TypeError, ValueError):
        raise AskError(
            f"{column.name} holds {kind.__name__} values: {text!r} is not one."
        ) from None
    return found


def ask(column: str, op: str, text: str) -> Filter:
    """One filter, as ``where_text`` writes it and ``parse_where`` reads it
    back the same; AskError otherwise (a comma, or a sign the value starts
    with, would read back as another)."""
    found = (column, op, text.strip())
    if op not in OPERATORS or parse_where(where_text([found])) != [found]:
        raise AskError(
            f"{text!r} cannot be a filter's value: a comma, or a sign at its "
            "start, would be read as another filter."
        )
    return found


def where_text(filters: Sequence[Filter]) -> str:
    """Filters as ``parse_where`` reads them back (``id:3, amount>=2000``)."""
    return ", ".join(f"{c}{op}{v}" for c, op, v in filters)


def parse_where(text: str | None) -> list[Filter]:
    """``column:value`` (equals) or ``column>=value`` (any of ``OPERATORS``),
    comma-separated, as filters (a value holding a comma cannot be asked
    for: keys are numbers and ids)."""
    found = (_FILTER.fullmatch(part) for part in (text or "").split(","))
    return [(m[1], m[2], m[3]) for m in found if m and m[3]]
