"""Picking a date, through the platform's own picker."""

from collections.abc import Callable
from datetime import date

import flet as ft

from app.components.frontend.controls.calendar import CalendarPanel
from app.components.frontend.controls.form_fields.text import FormTextField
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


class FormDateField(ft.Container):
    """A date input backed by a calendar, not a typed string.

    Every date in this app used to be a ``FormTextField`` labelled
    "(YYYY-MM-DD)", parsed on save and rejected with a snackbar if you
    mistyped it - which puts the format rule in a label and the
    enforcement in an error message, neither of which is where you are
    looking.

    The calendar is the house ``CalendarPanel``, NOT ``ft.DatePicker``:
    that one is a Flutter dialog themed through
    ``theme.date_picker_theme``, and setting that property at all crashes
    the page render on Flet 0.28.3 (bisected to a single plain
    ``bgcolor``). Ours is ordinary Containers wearing ``AegisTheme``.

    It expands INLINE, under the field, rather than floating in a
    ``Dropdown`` like the account filter and payee pickers. Those live on
    a page; this one lives in a dialog, and Flet renders ``page.overlay``
    BELOW ``ft.AlertDialog`` - so a floating panel opened from inside a
    dialog draws behind it and the dialog's own scrim swallows the
    clicks. Confirmed live. Growing the dialog is the trade for being
    reachable at all.

    The field shows the date the way the rest of the product shows dates
    ("Aug 19, 2026", ``core.formatting.format_date``) while ``value``
    stays ISO, so callers that already do
    ``date.fromisoformat(field.value)`` keep working unchanged.
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        hint: str = "Pick a date",
        width: int | None = None,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        if width is not None:
            self.width = width
        self._iso = (value or "").strip()
        self._on_change = on_change
        self._field = FormTextField(
            label=label,
            value=format_date(self._iso) if self._iso else "",
            hint=hint,
            width=width,
        )
        # Read-only: a calendar that also takes free text has two sources
        # of truth and one of them can be "Augsut 19".
        self._field._text_field.read_only = True
        self._field._text_field.suffix_icon = ft.Icons.CALENDAR_MONTH
        self._field._text_field.on_click = self._toggle
        self._panel = CalendarPanel(selected=self._parsed(), on_pick=self._picked)
        # Bordered like the popup it replaces, so it still reads as a
        # surface floating over the form rather than another form row.
        self._holder = ft.Container(
            content=self._panel,
            visible=False,
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            padding=Theme.Spacing.SM,
            margin=ft.margin.only(top=Theme.Spacing.XS),
        )
        self.content = ft.Column([self._field, self._holder], spacing=0, tight=True)

    def _parsed(self) -> date | None:
        if not self._iso:
            return None
        try:
            return date.fromisoformat(self._iso)
        except ValueError:
            return None

    @property
    def value(self) -> str:
        """The ISO date, or "" - what callers parse."""
        return self._iso

    @value.setter
    def value(self, new_value: str) -> None:
        self._iso = (new_value or "").strip()
        self._field.value = format_date(self._iso) if self._iso else ""

    def _toggle(self, _e: ft.ControlEvent) -> None:
        self._holder.visible = not self._holder.visible
        if self._holder.page is not None:
            self._holder.update()

    def _picked(self, day: date) -> None:
        self._iso = day.isoformat()
        self._field.value = format_date(self._iso)
        # Close on pick: the calendar has said all it has to say, and
        # leaving it open keeps the dialog at its tallest for no reason.
        self._holder.visible = False
        if self._field.page is not None:
            self._field.update()
        if self._holder.page is not None:
            self._holder.update()
        if self._on_change is not None:
            self._on_change(self._iso)
