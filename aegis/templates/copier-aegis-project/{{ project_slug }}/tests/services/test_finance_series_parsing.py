"""Parsing a pasted valuation series.

The real input is a block copied out of a listing site's history table.
Every line has to parse or raise: a silently dropped row is an invisible
dent in a net-worth chart, and whoever pasted it has no way to notice.
"""

from datetime import date

import pytest

from app.services.finance.domains.ledger.series_parsing import parse_series_lines


class TestListingSitePaste:
    def test_month_year_and_rounded_thousands(self) -> None:
        rows = parse_series_lines(
            "Date\tThis home\nAug 2026\t$711.2K\nJul 2026\t$708.5K\nJun 2026\t$711.5K\n"
        )

        assert rows == [
            (date(2026, 8, 1), 71_120_000),
            (date(2026, 7, 1), 70_850_000),
            (date(2026, 6, 1), 71_150_000),
        ]

    def test_the_header_is_skipped_only_before_data(self) -> None:
        """A stray unparseable line MID-series is an error, not a header."""
        with pytest.raises(ValueError):
            parse_series_lines("Aug 2026\t$711.2K\nnonsense\nJul 2026\t$708.5K\n")


class TestOtherShapes:
    def test_iso_dates_and_plain_numbers(self) -> None:
        rows = parse_series_lines("2026-08-01,711200\n2026-07-01,708500\n")

        assert rows == [
            (date(2026, 8, 1), 71_120_000),
            (date(2026, 7, 1), 70_850_000),
        ]

    def test_commas_dollars_and_cents(self) -> None:
        assert parse_series_lines("2026-08-01,$711,200.00") == [
            (date(2026, 8, 1), 71_120_000)
        ]

    def test_millions_suffix(self) -> None:
        assert parse_series_lines("2026-08-01,1.2M") == [
            (date(2026, 8, 1), 120_000_000)
        ]


class TestFailuresAreLoud:
    def test_an_empty_block_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_series_lines("   \n\n")

    def test_a_line_with_no_value_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_series_lines("Aug 2026\n")

    def test_an_unreadable_amount_names_the_line(self) -> None:
        with pytest.raises(ValueError, match="about a lot"):
            parse_series_lines("2026-08-01,about a lot")
