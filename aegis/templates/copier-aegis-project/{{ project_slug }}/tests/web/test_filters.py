"""Jinja filters: the only place templates format money, dates, percents.

Amounts arrive from the finance service as integer minor units with a
currency code; ``money`` is the port of the Flet ``_usd`` helper widened
to honour the code.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.components.web_frontend.filters import cents_to_input, money_to_cents
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


class TestMoneyRoundTrip:
    def test_money_to_cents_reads_what_people_type(self) -> None:
        assert money_to_cents("$1,200.50") == 120_050
        assert money_to_cents(" 12 ") == 1_200
        assert money_to_cents("") == 0
        assert money_to_cents("lots") is None

    def test_cents_to_input_is_the_inverse_for_form_values(self) -> None:
        assert cents_to_input(350_000_00) == "350,000.00"
        assert cents_to_input(None) == ""
        assert money_to_cents(cents_to_input(1_250_50)) == 1_250_50


class TestWindows:
    """The chip rows all speak one vocabulary (web_frontend/ranges.py)."""

    def test_since_is_the_cutoff_a_window_means(self) -> None:
        """UTC, the clock rows are stamped with, and no service import:
        the web frontend ships without any of them."""
        from app.components.web_frontend import ranges

        assert ranges.since(7) == datetime.now(UTC).date() - timedelta(days=7)
        assert ranges.since(ranges.ALL) is None
        assert ranges.since(None) is None

    def test_one_chip_row_serves_every_page(self) -> None:
        from app.components.web_frontend import ranges

        labels = [label for _days, label in ranges.WINDOWS]
        assert labels == ["1d", "7d", "14d", "1m", "3m", "1y", "All"]
        assert ranges.WINDOWS[-1][0] == ranges.ALL

    def test_all_becomes_the_page_ceiling_where_a_count_is_needed(self) -> None:
        """The ledger reads "everything" as no cutoff; the endpoints that
        take a day count read it as their own cap."""
        from app.components.web_frontend import ranges

        assert ranges.horizon(ranges.ALL, 730) == 730
        assert ranges.horizon(90, 730) == 90
        assert ranges.horizon(3650, 730) == 730
