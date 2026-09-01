"""Tests for ``app.core.formatting``.

Focused on ``format_relative_time`` since it has nontrivial branching and
parse-failure paths. The other formatters in this module
(``format_number``, ``format_cost``, ``format_percentage``) are too
trivial to test directly; their behavior is already covered transitively
by the CLI and dashboard tests that consume them.
"""

from datetime import UTC, datetime

from app.core.formatting import format_relative_time

NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


class TestFormatRelativeTime:
    def test_empty_returns_dash(self):
        assert format_relative_time("") == "—"
        assert format_relative_time(None) == "—"

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
