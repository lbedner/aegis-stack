"""Jinja filters: the only place templates format money, dates, percents.

Amounts arrive from the finance service as integer minor units with a
currency code; ``money`` is the port of the Flet ``_usd`` helper widened
to honour the code.
"""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pytest

from app.components.web_frontend.rendering import templates


@pytest.fixture
def money() -> Callable[..., str]:
    return templates.env.filters["money"]


@pytest.fixture
def short_date() -> Callable[..., str]:
    return templates.env.filters["short_date"]


@pytest.fixture
def pct() -> Callable[..., str]:
    return templates.env.filters["pct"]


class TestMoney:
    @pytest.mark.parametrize(
        ("cents", "expected"),
        [
            (123456, "$1,234.56"),
            (5, "$0.05"),
            (-5, "-$0.05"),
            (-123456, "-$1,234.56"),
            (0, "$0.00"),
            (None, "$0.00"),
        ],
    )
    def test_usd_matches_the_flet_register(
        self, money: Callable[..., str], cents: int | None, expected: str
    ) -> None:
        assert money(cents) == expected

    def test_known_currencies_use_their_symbol(self, money: Callable[..., str]) -> None:
        assert money(100, "EUR") == "€1.00"
        assert money(100, "GBP") == "£1.00"

    def test_zero_decimal_currencies_have_no_cents(
        self, money: Callable[..., str]
    ) -> None:
        assert money(1500, "JPY") == "¥1,500"

    def test_unknown_currency_falls_back_to_its_code(
        self, money: Callable[..., str]
    ) -> None:
        assert money(100, "CHF") == "CHF 1.00"


class TestShortDate:
    TODAY = date(2026, 9, 7)

    def test_this_year_drops_the_year(self, short_date: Callable[..., str]) -> None:
        assert short_date(date(2026, 7, 15), today=self.TODAY) == "Jul 15"

    def test_other_years_keep_it(self, short_date: Callable[..., str]) -> None:
        assert short_date(date(2025, 12, 31), today=self.TODAY) == "Dec 31, 2025"

    def test_accepts_iso_strings_and_datetimes(
        self, short_date: Callable[..., str]
    ) -> None:
        assert short_date("2026-07-15", today=self.TODAY) == "Jul 15"
        assert short_date(datetime(2026, 7, 15, 13, 5), today=self.TODAY) == "Jul 15"

    def test_blank_stays_blank(self, short_date: Callable[..., str]) -> None:
        assert short_date(None) == ""
        assert short_date("") == ""


class TestPct:
    @pytest.mark.parametrize(
        ("ratio", "digits", "expected"),
        [(0.153, 0, "15%"), (0.153, 1, "15.3%"), (1.0, 0, "100%"), (0, 0, "0%")],
    )
    def test_formats_a_ratio(
        self, pct: Callable[..., str], ratio: float, digits: int, expected: str
    ) -> None:
        assert pct(ratio, digits) == expected

    def test_blank_stays_blank(self, pct: Callable[..., Any]) -> None:
        assert pct(None) == ""
