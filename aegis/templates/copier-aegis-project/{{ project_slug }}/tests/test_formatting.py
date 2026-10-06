"""Tests for ``app.core.formatting``.

Focused on ``format_relative_time`` since it has nontrivial branching and
parse-failure paths. The other formatters in this module
(``format_number``, ``format_cost``, ``format_percentage``) are too
trivial to test directly; their behavior is already covered transitively
by the CLI and dashboard tests that consume them.
"""

from datetime import UTC, datetime

import pytest

from app.core.formatting import format_relative_time, split_matches

NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


class TestFormatRelativeTime:
    def test_empty_returns_dash(self):
        assert format_relative_time("") == "—"
        assert format_relative_time(None) == "—"

    def test_takes_a_datetime_as_well_as_iso_text(self):
        """Model columns are datetimes; callers pass them as they are."""
        aware = datetime(2026, 5, 19, 11, 55, tzinfo=UTC)
        naive = datetime(2026, 5, 19, 9, 0)
        assert format_relative_time(aware, now=NOW) == "5 minutes ago"
        assert format_relative_time(naive, now=NOW) == "3 hours ago"

    def test_just_now_under_one_minute(self):
        ts = "2026-05-19T11:59:30+00:00"  # 30s before NOW
        assert format_relative_time(ts, now=NOW) == "just now"

    def test_minutes_singular_and_plural(self):
        assert format_relative_time("2026-05-19T11:59:00+00:00", now=NOW) == (
            "1 minute ago"
        )
        assert format_relative_time("2026-05-19T11:55:00+00:00", now=NOW) == (
            "5 minutes ago"
        )

    def test_hours_singular_and_plural(self):
        assert format_relative_time("2026-05-19T11:00:00+00:00", now=NOW) == (
            "1 hour ago"
        )
        assert format_relative_time("2026-05-19T09:00:00+00:00", now=NOW) == (
            "3 hours ago"
        )

    def test_falls_back_to_short_absolute_after_one_day(self):
        """``%b %d %H:%M`` is what observability already used; preserve it."""
        result = format_relative_time("2026-05-15T08:30:00+00:00", now=NOW)
        # Match "May 15 08:30"
        assert "May" in result
        assert "15" in result
        assert "08:30" in result

    def test_coarse_keeps_counting_past_a_day(self):
        """Opt-in mode for ages measured in months, not minutes.

        An installed model is typically months old, and "Jan 21 02:54"
        answers a question nobody asked - ``ollama list`` says "6 months
        ago" because that is the readable unit at that distance. Default
        behaviour is untouched so no existing caller shifts.
        """
        assert format_relative_time(
            "2026-05-16T12:00:00+00:00", now=NOW, coarse=True
        ) == ("3 days ago")
        assert format_relative_time(
            "2026-05-18T12:00:00+00:00", now=NOW, coarse=True
        ) == ("1 day ago")

    def test_coarse_reads_in_months_then_years(self):
        assert format_relative_time(
            "2025-11-19T12:00:00+00:00", now=NOW, coarse=True
        ) == ("6 months ago")
        assert format_relative_time(
            "2024-05-19T12:00:00+00:00", now=NOW, coarse=True
        ) == ("2 years ago")

    def test_coarse_never_reports_zero_months(self):
        """A 30-day gap is "1 month", not "0 months" - integer division
        by 30.44 rounds a real duration down to nothing."""
        result = format_relative_time("2026-04-19T12:00:00+00:00", now=NOW, coarse=True)
        assert result == "1 month ago"

    def test_coarse_leaves_the_sub_day_branches_alone(self):
        assert format_relative_time(
            "2026-05-19T09:00:00+00:00", now=NOW, coarse=True
        ) == ("3 hours ago")

    def test_trailing_z_is_accepted(self):
        """``Z`` suffix isn't accepted by ``fromisoformat`` on every
        Python the project targets — the formatter normalizes it."""
        ts = "2026-05-19T11:55:00Z"
        assert format_relative_time(ts, now=NOW) == "5 minutes ago"

    def test_missing_timezone_treated_as_utc(self):
        """A naive ISO string (no offset) is assumed UTC rather than
        crashing with a tz-aware vs naive comparison error."""
        ts = "2026-05-19T11:55:00"
        assert format_relative_time(ts, now=NOW) == "5 minutes ago"

    def test_unparseable_returns_raw_input(self):
        """Returning the raw input keeps the value visible in the UI for
        debugging rather than silently disappearing into a dash."""
        assert format_relative_time("not-a-date", now=NOW) == "not-a-date"

    def test_production_default_now_is_used(self):
        """Sanity: omitting ``now`` doesn't crash. We can't assert a
        specific bucket because real time moves, but a fresh timestamp
        should land in ``just now``."""
        from datetime import datetime as _dt

        ts = _dt.now(UTC).isoformat()
        assert format_relative_time(ts) == "just now"


class TestFormatBytes:
    def test_it_picks_the_unit_that_reads(self):
        from app.core.formatting import format_bytes

        assert format_bytes(0) == "0 B"
        assert format_bytes(512) == "512 B"
        assert format_bytes(9_400_000) == "9.0 MB"
        assert format_bytes(222_298_112) == "212.0 MB"
        assert format_bytes(3 * 1024**3) == "3.0 GB"


def test_format_span_reads_in_its_two_largest_units() -> None:
    from app.core.formatting import format_span

    assert format_span(8) == "8s"
    assert format_span(125) == "2m 5s"
    assert format_span(3720) == "1h 2m"
    assert format_span(90061) == "1d 1h"
    assert format_span(None) is None


class TestSafeFilename:
    """A name bound for Content-Disposition cannot end the header or the
    quoted value: a newline there is header injection."""

    def test_line_breaks_quotes_and_backslashes_are_dropped(self) -> None:
        from app.core.formatting import safe_filename

        assert safe_filename('bad"\r\nSet-Cookie: x\\.pdf') == "badSet-Cookie: x.pdf"

    def test_an_empty_result_falls_back(self) -> None:
        from app.core.formatting import safe_filename

        assert safe_filename('\r\n"', fallback="download") == "download"


# Each chart format's reading, for format_value and its browser twin
# (charts.js formatValue, tests/web/test_charts_js.py).
CHART_FORMATS = [
    (12.5, "percent", "12.5%"),
    (128 * 2**20, "bytes", "128.0 MB"),
    (2048, "bytes_per_second", "2.0 KB/s"),
    (512, "bytes_per_second", "512 B/s"),
    (1.24, "seconds", "1.2 s"),
    (70.4, "seconds", "70 s"),
    (-1234.5, "money", "-$1,234.50"),
    (1234, None, "1,234"),
]


@pytest.mark.parametrize(("value", "fmt", "expected"), CHART_FORMATS)
def test_a_charted_value_reads_in_its_charts_format(
    value: float, fmt: str | None, expected: str
) -> None:
    from app.core.formatting import format_value

    assert format_value(value, fmt) == expected


# A search's matches, for split_matches and its browser twin (app.js
# splitMatches, the client-side filter: tests/web/test_app_js.py).
MATCH_CASES = [
    (
        "Write failed, write again",
        "WRITE",
        [("Write", True), (" failed, ", False), ("write", True), (" again", False)],
    ),
    ("Write failed", "", [("Write failed", False)]),
    ("Write failed", "nothing", [("Write failed", False)]),
    ("a.b (c)", ".b (", [("a", False), (".b (", True), ("c)", False)]),
]


@pytest.mark.parametrize(("text", "query", "runs"), MATCH_CASES)
def test_split_matches_marks_every_match_whatever_its_case(
    text: str, query: str, runs: list[tuple[str, bool]]
) -> None:
    assert split_matches(text, query) == runs


@pytest.mark.parametrize(
    ("count", "expected"), [(0, "0 drafts"), (1, "1 draft"), (2, "2 drafts")]
)
def test_a_count_takes_its_noun_singular_only_for_one(
    count: int, expected: str
) -> None:
    from app.core.formatting import counted

    assert counted(count, "draft") == expected


def test_a_noun_whose_plural_is_not_an_s_names_it() -> None:
    from app.core.formatting import counted

    assert counted(1, "watch", "watches") == "1 watch"
    assert counted(3, "watch", "watches") == "3 watches"
