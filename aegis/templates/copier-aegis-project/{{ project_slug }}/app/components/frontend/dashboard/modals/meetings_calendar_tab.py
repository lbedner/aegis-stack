"""Meetings > Calendar in the Flet Overseer: every agent's calendar, a month
at a time, each meeting a line in its agent's color. The same month as the
htmx Overseer's Calendar, over the admin API (``api/meetings/admin.py``),
in UTC: the Flet app renders on the server, which does not know the
viewer's time zone.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.calendar import month_grid, shift_month
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.core.time import today

from .modal_sections import ChartColors, EmptyStatePlaceholder

CALENDAR = "/api/v1/meetings/admin/calendar"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def month_params(anchor: date) -> dict[str, str]:
    """The admin API's query for ``anchor``'s month: its whole weeks."""
    weeks = month_grid(anchor.year, anchor.month)
    return {
        "first": weeks[0][0].isoformat(),
        "last": weeks[-1][-1].isoformat(),
        "tz": "UTC",
    }


def _start(entry: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(entry["starts_at"]))


def by_day(entries: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    """The admin API's meetings, by the day each starts on, in order."""
    days: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for entry in sorted(entries, key=_start):
        days[_start(entry).date()].append(entry)
    return days


def entry_line(entry: dict[str, Any]) -> str:
    """One meeting as its day shows it: ``09:00 Standup``."""
    return f"{_start(entry):%H:%M} {entry.get('title') or '(No title)'}"


class CalendarTab(ft.Container):
    """A month of every agent's meetings, moved a month at a time."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._today = today()
        self._month = self._today.replace(day=1)
        self._heading = ft.Text(
            "",
            size=Theme.Typography.H3,
            weight=ft.FontWeight.W_600,
            color=Theme.Colors.TEXT_PRIMARY,
        )
        self._grid = ft.Container(
            content=EmptyStatePlaceholder("Loading the calendar..."), expand=True
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        self._nav(ft.Icons.CHEVRON_LEFT, -1),
                        ft.TextButton("Today", on_click=self._go_today),
                        self._nav(ft.Icons.CHEVRON_RIGHT, 1),
                        self._heading,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._grid,
                SecondaryText(
                    "Times in UTC. Each agent's calendar, read every minute.",
                    size=Theme.Typography.BODY_SMALL,
                ),
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    def _nav(self, icon: str, delta: int) -> ft.Control:
        async def step(_e: ft.ControlEvent) -> None:
            self._month = shift_month(self._month, delta)
            await self._load()

        return ft.IconButton(
            icon=icon,
            icon_size=18,
            icon_color=Theme.Colors.TEXT_SECONDARY,
            on_click=step,
        )

    async def _go_today(self, _e: ft.ControlEvent) -> None:
        self._month = self._today.replace(day=1)
        await self._load()

    async def _load(self) -> None:
        api = get_session_state(self.page).api_client
        data = await api.get(CALENDAR, params=month_params(self._month))
        days = by_day(data if isinstance(data, list) else [])
        self._heading.value = (
            f"{calendar.month_name[self._month.month]} {self._month.year}"
        )
        weeks = month_grid(self._month.year, self._month.month)
        self._grid.content = ft.Column(
            [
                ft.Row([self._weekday(name) for name in WEEKDAYS], spacing=2),
                *(
                    ft.Row([self._day(d, days.get(d, [])) for d in week], spacing=2)
                    for week in weeks
                ),
            ],
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        # ``_load`` starts before the tab is mounted: update only once it is.
        if self.page and self._heading.page:
            self.update()

    def _weekday(self, name: str) -> ft.Control:
        return ft.Container(
            content=SecondaryText(name, size=Theme.Typography.BODY_SMALL),
            expand=1,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.XS),
        )

    def _day(self, day: date, entries: list[dict[str, Any]]) -> ft.Control:
        outside = day.month != self._month.month
        today = day == self._today
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        str(day.day),
                        size=Theme.Typography.BODY_SMALL,
                        weight=ft.FontWeight.W_600 if today else None,
                        color=Theme.Colors.ACCENT
                        if today
                        else (
                            Theme.Colors.TEXT_SECONDARY
                            if outside
                            else Theme.Colors.TEXT_PRIMARY
                        ),
                    ),
                    *(self._entry(e) for e in entries),
                ],
                spacing=2,
                tight=True,
            ),
            expand=1,
            height=96,
            padding=Theme.Spacing.XS,
            border=ft.border.all(
                1, Theme.Colors.ACCENT if today else Theme.Colors.BORDER_DEFAULT
            ),
            border_radius=4,
            bgcolor=None if outside else Theme.Colors.SURFACE_1,
        )

    def _entry(self, entry: dict[str, Any]) -> ft.Control:
        color = ChartColors.RAMP[
            (int(entry.get("color") or 1) - 1) % len(ChartColors.RAMP)
        ]
        return ft.Container(
            content=ft.Text(
                entry_line(entry),
                size=Theme.Typography.BODY_SMALL,
                color=Theme.Colors.TEXT_PRIMARY,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            tooltip=f"{entry.get('agent')}, {entry.get('state')}",
            border=ft.border.only(left=ft.BorderSide(3, color)),
            padding=ft.padding.only(left=4),
        )
