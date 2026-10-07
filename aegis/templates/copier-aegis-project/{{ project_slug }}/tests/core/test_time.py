"""The shared clock and its storage form."""

from datetime import datetime


class TestAsStored:
    def test_an_aware_value_becomes_naive_utc_at_the_same_instant(self) -> None:
        from datetime import timedelta, timezone

        from app.core.time import as_stored

        plus_two = datetime(2026, 9, 22, 14, 0, tzinfo=timezone(timedelta(hours=2)))

        assert as_stored(plus_two) == datetime(2026, 9, 22, 12, 0)

    def test_a_naive_value_is_already_stored_form(self) -> None:
        from app.core.time import as_stored

        naive = datetime(2026, 9, 22, 12, 0)

        assert as_stored(naive) is naive


# Calendar reads written out by hand: the host's local date (a day apart
# from UTC for part of every evening), and UTC ones that bypass the clock.
CLOCK_READS = (
    "date.today()",
    "datetime.now().date()",
    "datetime.now(UTC).date()",
    "utcnow().date()",
)
# The clocks themselves: core's, and finance's, which its tests pin. A
# date picker highlights the person's own today, so it reads the local date.
CLOCKS = ("core/time.py", "services/finance/utils.py", "components/frontend/controls/calendar.py")


def test_the_app_reads_the_calendar_through_its_clock() -> None:
    """``app.core.time.today()`` (finance: ``current_date()``) is the one
    source of today's date, so a test can pin it and no page shows
    yesterday for the hours each evening when local and UTC disagree."""
    from pathlib import Path

    import app

    root = Path(app.__file__).parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if not str(path.relative_to(root)).endswith(CLOCKS)
        and any(read in path.read_text() for read in CLOCK_READS)
    ]
    assert offenders == [], f"calendar reads (use app.core.time.today): {offenders}"
