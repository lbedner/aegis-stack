"""The house month calendar.

Replaces ``ft.DatePicker``, which cannot be themed on Flet 0.28.3 without
crash-looping the page render. The grid maths is separated from the
rendering so the part that is actually easy to get wrong - which day lands
in which cell, and what a month step does at a year boundary - is testable
without a page.
"""

from datetime import date

from app.components.frontend.controls.calendar import (
    CalendarPanel,
    month_grid,
    shift_month,
)


class TestMonthGrid:
    def test_every_week_is_a_full_row(self) -> None:
        """Leading/trailing cells come from the neighbouring months so the
        grid never changes shape mid-month."""
        for month in range(1, 13):
            weeks = month_grid(2026, month)
            assert all(len(week) == 7 for week in weeks), month

    def test_the_grid_brackets_the_month(self) -> None:
        weeks = month_grid(2026, 8)
        assert weeks[0][0] <= date(2026, 8, 1)
        assert weeks[-1][-1] >= date(2026, 8, 31)

    def test_weeks_start_on_monday(self) -> None:
        for week in month_grid(2026, 8):
            assert week[0].weekday() == 0

    def test_february_in_a_leap_year(self) -> None:
        days = [d for week in month_grid(2024, 2) for d in week if d.month == 2]
        assert len(days) == 29


class TestShiftMonth:
    def test_it_rolls_over_a_year_boundary(self) -> None:
        assert shift_month(date(2026, 12, 1), 1) == date(2027, 1, 1)
        assert shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)

    def test_it_never_invents_a_31st_of_february(self) -> None:
        """Anchoring to the 1st is why - clamp, skip and overflow all
        surprise somebody."""
        assert shift_month(date(2026, 1, 31), 1) == date(2026, 2, 1)

    def test_a_year_in_either_direction(self) -> None:
        assert shift_month(date(2026, 6, 1), 12) == date(2027, 6, 1)
        assert shift_month(date(2026, 6, 1), -12) == date(2025, 6, 1)


class TestCalendarPanel:
    def test_it_opens_on_the_selected_month(self) -> None:
        panel = CalendarPanel(
            selected=date(2026, 8, 12), on_pick=lambda d: None, today=date(2026, 1, 1)
        )
        assert panel._heading.value == "August 2026"

    def test_it_opens_on_today_when_nothing_is_selected(self) -> None:
        panel = CalendarPanel(on_pick=lambda d: None, today=date(2026, 3, 4))
        assert panel._heading.value == "March 2026"

    def test_stepping_changes_the_month(self) -> None:
        panel = CalendarPanel(on_pick=lambda d: None, today=date(2026, 12, 4))
        panel._step(1)
        assert panel._heading.value == "January 2027"

    def test_picking_reports_the_date(self) -> None:
        picked: list[date] = []
        panel = CalendarPanel(on_pick=picked.append, today=date(2026, 8, 1))
        panel._pick(date(2026, 8, 19))
        assert picked == [date(2026, 8, 19)]
