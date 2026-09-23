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
