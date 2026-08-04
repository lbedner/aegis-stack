"""A month calendar built from house controls.

Flet ships ``ft.DatePicker``, but it is a Flutter DIALOG themed through
``theme.date_picker_theme`` - and setting that property at all crashes the
page render on Flet 0.28.3 ("Null check operator used on a null value" at
route=/, reconnect-looping). Bisected to a single plain ``bgcolor``, so
there is no safe subset to reach for. Left untouched, the picker renders
as stock Material in the middle of a near-black app.

So the calendar is ours: ordinary Containers and Texts wearing
``AegisTheme``, shown through the same anchored ``Dropdown`` popup the
account filter and the payee picker already use. It inherits the app's
surface, border, radius and accent for free, and cannot be broken by a
theme property Flet mis-serializes.

The grid maths is deliberately separable from the rendering
(``month_grid``) - which day lands in which cell, and how a month rolls
over a year boundary, is the part worth testing without a page.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

# Monday-first weeks, matching the ISO week the rest of the app reasons in.
_CAL = calendar.Calendar(firstweekday=0)
_WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
_CELL = 34
# 7 cells + the panel's own padding. Fixed so the grid does not reflow
# between a 5-row month and a 6-row one.
PANEL_WIDTH = _CELL * 7 + 24


def month_grid(year: int, month: int) -> list[list[date]]:
    """Weeks of seven dates covering ``year``/``month``.

    Leading and trailing cells belong to the neighbouring months (they are
    rendered muted, not blank) so every week is a full row and the grid
    never changes shape mid-month.
    """
    weeks = _CAL.monthdatescalendar(year, month)
    return [list(week) for week in weeks]


def shift_month(anchor: date, delta: int) -> date:
    """``anchor`` moved ``delta`` months, clamped to the 1st.

    Anchored to day 1 on purpose: stepping from 31 Jan would otherwise
    have to invent a 31 Feb, and every strategy for that (clamp, skip,
    overflow) surprises someone.
    """
    index = (anchor.year * 12 + anchor.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


class CalendarPanel(ft.Container):
    """One month, with prev/next and a Today shortcut."""

    def __init__(
        self,
        *,
        selected: date | None = None,
        on_pick: Callable[[date], None],
        today: date | None = None,
    ) -> None:
        super().__init__()
        self._on_pick = on_pick
        self._today = today or date.today()
        self._selected = selected
        self._cursor = (selected or self._today).replace(day=1)
        self.width = PANEL_WIDTH
        self._heading = ft.Text(
            "",
            size=Theme.Typography.BODY,
            weight=ft.FontWeight.W_600,
            color=Theme.Colors.TEXT_PRIMARY,
        )
        self._grid = ft.Column(spacing=2, tight=True)
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        self._nav(ft.Icons.CHEVRON_LEFT, -1),
                        ft.Container(content=self._heading, expand=True),
                        self._nav(ft.Icons.CHEVRON_RIGHT, 1),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                ),
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(
                                day,
                                size=Theme.Typography.BODY_SMALL,
                                color=Theme.Colors.TEXT_SECONDARY,
                            ),
                            width=_CELL,
                            alignment=ft.alignment.center,
                        )
                        for day in _WEEKDAYS
                    ],
                    spacing=0,
                ),
                self._grid,
            ],
            spacing=Theme.Spacing.SM,
            tight=True,
        )
        self._render()

    def _nav(self, icon: str, delta: int) -> ft.Control:
        return ft.IconButton(
            icon=icon,
            icon_size=18,
            icon_color=Theme.Colors.TEXT_SECONDARY,
            on_click=lambda _e, d=delta: self._step(d),
        )

    def _step(self, delta: int) -> None:
        self._cursor = shift_month(self._cursor, delta)
        self._render()
        if self.page is not None:
            self.update()

    def _render(self) -> None:
        self._heading.value = f"{calendar.month_name[self._cursor.month]} {self._cursor.year}"
        self._grid.controls = [
            ft.Row(
                [self._day(day) for day in week],
                spacing=0,
            )
            for week in month_grid(self._cursor.year, self._cursor.month)
        ]

    def _day(self, day: date) -> ft.Control:
        in_month = day.month == self._cursor.month
        is_selected = self._selected is not None and day == self._selected
        is_today = day == self._today
        if is_selected:
            color = ft.Colors.BLACK
        elif in_month:
            color = Theme.Colors.TEXT_PRIMARY
        else:
            # Neighbouring months stay visible but recede - a blank cell
            # makes the grid read as broken rather than as context.
            color = Theme.Colors.TEXT_SECONDARY
        return ft.Container(
            content=ft.Text(
                str(day.day),
                size=Theme.Typography.BODY_SMALL,
                color=color,
                weight=ft.FontWeight.W_600 if is_selected or is_today else None,
            ),
            width=_CELL,
            height=_CELL,
            alignment=ft.alignment.center,
            border_radius=_CELL / 2,
            bgcolor=Theme.Colors.ACCENT if is_selected else None,
            # Today is OUTLINED and the selection is FILLED, so the two
            # never have to be told apart by shade alone.
            border=(
                ft.border.all(1, Theme.Colors.ACCENT)
                if is_today and not is_selected
                else None
            ),
            ink=True,
            on_click=lambda _e, d=day: self._pick(d),
        )

    def _pick(self, day: date) -> None:
        self._selected = day
        self._cursor = day.replace(day=1)
        self._render()
        if self.page is not None:
            self.update()
        self._on_pick(day)
