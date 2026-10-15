"""What a filter on a table's rows may ask (``db_filters``): which
comparisons a column's kind allows (the one rule the page offers and the
server keeps), and filters as the URL carries them, back the same."""

import pytest

from app.services.system import db_filters
from tests.services._db_fixtures import LEDGER, MEMBER


def test_a_column_is_asked_what_its_kind_allows() -> None:
    """Numbers and dates are ordered too; text and flags only matched."""
    every = list(db_filters.OPERATORS)
    assert db_filters.operators(MEMBER.c.input_tokens) == every
    assert db_filters.operators(LEDGER.c.at) == every
    assert db_filters.operators(MEMBER.c.bio) == [":", "!="]
    assert db_filters.operators(MEMBER.c.active) == [":", "!="]


def test_a_filter_reads_back_as_it_was_written() -> None:
    """``column:value`` for equals (the row links'), the rest by their sign."""
    pairs = [("amount", ">=", "2000"), ("reason", ":", "fraud"), ("id", "!=", "3")]
    text = db_filters.where_text(pairs)
    assert text == "amount>=2000, reason:fraud, id!=3"
    assert db_filters.parse_where(text) == pairs


def test_a_filter_asked_is_one_the_text_carries_back() -> None:
    """A comma, or a sign the value starts with, would read back as another."""
    assert db_filters.ask("id", ":", " 3 ") == ("id", ":", "3")
    for op, value in ((":", "a,b"), (">", "=5"), ("~", "x")):
        with pytest.raises(db_filters.AskError):
            db_filters.ask("id", op, value)
