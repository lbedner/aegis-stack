"""The app's one set of time windows (``app.core.ranges``)."""

from datetime import timedelta

from app.core import ranges
from app.core.time import today


class TestWindows:
    """The chip rows and the reads that take a window all speak one
    vocabulary."""

    def test_since_is_the_cutoff_a_window_means(self) -> None:
        """The app's one clock (``app.core.time.today``), UTC like the rows."""

        assert ranges.since(7) == today() - timedelta(days=7)
        assert ranges.since(ranges.ALL) is None
        assert ranges.since(None) is None

    def test_one_chip_row_serves_every_page(self) -> None:
        labels = [label for _days, label in ranges.WINDOWS]
        assert labels == ["1d", "7d", "14d", "1m", "3m", "1y", "All"]
        assert ranges.WINDOWS[-1][0] == ranges.ALL

    def test_a_reader_names_days_never_the_everything_stand_in(self) -> None:
        assert ranges.DAYS == (1, 7, 14, 30, 90, 365)
