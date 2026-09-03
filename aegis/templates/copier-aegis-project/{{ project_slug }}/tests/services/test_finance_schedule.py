"""One answer to "when does this stream move money", for every caller.

The forecast, the month-ahead outlook, and anything else that walks a
stream forward each had their own loop. They drifted, and the drift was
always the same shape: a rule the recurring branch followed and the
one-time branch did not, or the other way round. Overdue money was
dropped from the outlook and from one-time bills in the forecast, and
a short window still charged a month-end budget.

The rules, stated once:

- a stream with no expected date has no occurrences
- an occurrence dated before today is money still owed, so it lands on
  today and remembers the day it was due
- only the LATEST miss carries: older ones are already in the balance
- everything from today to the horizon lands on its own date
"""

from datetime import date, timedelta

from app.services.finance.domains.planning.recurring.schedule import occurrences

TODAY = date(2026, 9, 3)
HORIZON = date(2026, 10, 3)


class _Stream:
    """The three fields the schedule reads."""

    def __init__(self, frequency: str, next_expected_date: date | None) -> None:
        self.frequency = frequency
        self.next_expected_date = next_expected_date


def _dates(stream) -> list[tuple[date, date]]:
    return [
        (o.lands_on, o.due_on)
        for o in occurrences(stream, today=TODAY, through=HORIZON)
    ]


def test_a_stream_with_no_date_has_no_occurrences() -> None:
    assert _dates(_Stream("monthly", None)) == []


def test_an_unknown_cadence_has_no_occurrences() -> None:
    assert _dates(_Stream("fortnightly-ish", TODAY)) == []


class TestOneTime:
    def test_a_future_bill_lands_on_its_own_date(self) -> None:
        due = date(2026, 9, 20)
        assert _dates(_Stream("once", due)) == [(due, due)]

    def test_an_overdue_bill_lands_on_today_and_remembers(self) -> None:
        due = date(2026, 8, 31)
        assert _dates(_Stream("once", due)) == [(TODAY, due)]

    def test_one_beyond_the_horizon_is_not_yet_our_problem(self) -> None:
        assert _dates(_Stream("once", date(2026, 12, 1))) == []


class TestRecurring:
    def test_it_lands_on_each_date_through_the_horizon(self) -> None:
        """Sep 10 is inside a one-month window; Oct 10 is not."""
        assert _dates(_Stream("monthly", date(2026, 9, 10))) == [
            (date(2026, 9, 10), date(2026, 9, 10)),
        ]

    def test_the_latest_miss_carries_to_today(self) -> None:
        landed = _dates(_Stream("monthly", date(2026, 8, 15)))
        assert landed[0] == (TODAY, date(2026, 8, 15))
        assert landed[1][0] == date(2026, 9, 15), "and the real one still follows"

    def test_a_miss_carries_even_when_the_next_one_is_today(self) -> None:
        """The boundary the carry rule is easiest to lose.

        A weekly bill missed last Thursday falls due again exactly today.
        Both are owed, and the earlier one has to keep the date it
        slipped - a walk that only carries a miss when the NEXT
        occurrence is strictly in the future swallows it here, and the
        row that would have said "due Aug 27" disappears.
        """
        landed = _dates(_Stream("weekly", TODAY - timedelta(days=7)))

        assert landed[:2] == [
            (TODAY, TODAY - timedelta(days=7)),
            (TODAY, TODAY),
        ]
        assert landed[2] == (TODAY + timedelta(days=7),) * 2, (
            "and the weekly run continues from there"
        )

    def test_older_misses_stay_behind(self) -> None:
        """Two months late carries once, not twice: the earlier one is
        already inside today's balance."""
        landed = _dates(_Stream("monthly", date(2026, 6, 15)))
        carried = [o for o in landed if o[0] == TODAY]
        assert len(carried) == 1
        assert carried[0][1] == date(2026, 8, 15), "the most recent miss, not the first"


def test_it_does_not_run_away_on_a_daily_cadence_and_a_long_window() -> None:
    """A guard exists so a bad cadence cannot spin; it must not fire on
    an ordinary year of a weekly bill."""
    weekly = _Stream("weekly", date(2026, 9, 4))
    landed = occurrences(weekly, today=TODAY, through=date(2027, 9, 3))
    assert len(list(landed)) == 53
