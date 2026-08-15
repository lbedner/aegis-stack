"""The pause surface on Bills & Income.

A paused bill must LOOK paused (its own status, with the until-date and
the why in reach), and the quick picks must land on real calendar
months - "3 months" from Aug 9 is Nov 9, not 90 days of drift.
"""

from datetime import date

from app.components.frontend.dashboard.modals.finance_recurring_tab import (
    _status_key,
    pause_options,
    stream_is_paused,
)


class TestPauseOptions:
    def test_the_quick_picks_are_calendar_months(self) -> None:
        today = date(2026, 8, 9)
        options = dict(pause_options(today))
        assert options["1 month"] == date(2026, 9, 9)
        assert options["3 months"] == date(2026, 11, 9)
        assert options["6 months"] == date(2027, 2, 9)

    def test_month_end_clamps_rather_than_overflows(self) -> None:
        options = dict(pause_options(date(2026, 8, 31)))
        assert options["1 month"] == date(2026, 9, 30)


class TestStreamIsPaused:
    def test_a_future_date_reads_paused(self) -> None:
        assert stream_is_paused({"paused_until": "2099-01-01"}) is True

    def test_a_lapsed_date_reads_active(self) -> None:
        assert stream_is_paused({"paused_until": "2020-01-01"}) is False

    def test_no_date_reads_active(self) -> None:
        assert stream_is_paused({}) is False
        assert stream_is_paused({"paused_until": None}) is False


class TestTheRowSaysPaused:
    def test_paused_outranks_the_curation_states(self) -> None:
        stream = {
            "paused_until": "2099-01-01",
            "direction": "outflow",
            "is_user_confirmed": True,
        }
        assert _status_key(stream) == "paused"

    def test_muted_still_outranks_paused(self) -> None:
        """Mute is the stronger silence (indefinite); a row that is both
        reads as the thing that lasts longer."""
        stream = {"is_muted": True, "paused_until": "2099-01-01"}
        assert _status_key(stream) == "muted"

    def test_a_lapsed_pause_leaves_no_trace_on_the_row(self) -> None:
        stream = {
            "paused_until": "2020-01-01",
            "direction": "outflow",
            "is_user_confirmed": True,
        }
        assert _status_key(stream) == "good"


class TestIndefinitePause:
    """"Can we have an indefinite one?" - yes, and NOT as NULL: a null
    ``paused_until`` already means "not paused" in every consumer, so
    indefinite is a sentinel date that never arrives. Every comparison,
    endpoint and serialization works unchanged; only display knows.
    """

    def test_the_sentinel_reads_as_paused_forever(self) -> None:
        from app.services.finance.constants import PAUSE_INDEFINITE

        assert stream_is_paused({"paused_until": PAUSE_INDEFINITE.isoformat()})

    def test_the_label_says_indefinitely_not_the_year_9999(self) -> None:
        from app.components.frontend.dashboard.modals.finance_recurring_tab import (
            pause_label,
        )
        from app.services.finance.constants import PAUSE_INDEFINITE

        assert pause_label(PAUSE_INDEFINITE.isoformat()) == "indefinitely"
        assert pause_label("2026-11-09") == "until 2026-11-09"
