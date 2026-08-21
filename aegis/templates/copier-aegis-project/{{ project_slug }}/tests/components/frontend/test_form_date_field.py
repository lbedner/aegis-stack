"""The calendar-backed date input.

Its contract is a split one: what the user READS is the humanized date the
rest of the product shows ("Aug 12, 2026"), what callers GET is ISO. Every
existing call site already does ``date.fromisoformat(field.value)``, so
breaking that half turns a display change into a save bug.
"""

from datetime import date
import inspect

import flet as ft

from app.components.frontend.controls.form_fields import FormDateField
from app.components.frontend.dashboard.modals.finance_recurring_tab import (
            dialogs,
            editor,
        )


class TestValueContract:
    def test_value_is_iso_and_the_display_is_human(self) -> None:
        field = FormDateField(label="Next due date", value="2026-08-12")
        assert field.value == "2026-08-12"
        assert field._field.value == "Aug 12, 2026"

    def test_the_setter_keeps_both_halves_in_step(self) -> None:
        field = FormDateField(label="Next due date", value="2026-08-12")
        field.value = "2026-12-25"
        assert field.value == "2026-12-25"
        assert field._field.value == "Dec 25, 2026"

    def test_empty_stays_empty_rather_than_showing_a_fake_date(self) -> None:
        field = FormDateField(label="Next due date")
        assert field.value == ""
        assert field._field.value == ""

    def test_the_input_cannot_be_typed_into(self) -> None:
        """A calendar that also takes free text has two sources of truth,
        and one of them can be "Augsut 19"."""
        field = FormDateField(label="Next due date")
        assert field._field._text_field.read_only is True
        assert field._field._text_field.suffix_icon == ft.Icons.CALENDAR_MONTH

    def test_the_calendar_is_inline_not_floating(self) -> None:
        """Flet renders page.overlay BELOW ft.AlertDialog, so a floating
        panel opened from inside a dialog draws behind it and the scrim
        eats the clicks. Confirmed live. Inline is what makes it
        reachable at all."""
        from app.components.frontend.controls.calendar import CalendarPanel
        from app.components.frontend.controls.dropdown import Dropdown

        field = FormDateField(label="Next due date")
        assert isinstance(field._panel, CalendarPanel)
        assert not isinstance(field.content, Dropdown)
        assert field._holder in field.content.controls

    def test_the_calendar_starts_closed_and_toggles(self) -> None:
        field = FormDateField(label="Next due date")
        assert field._holder.visible is False
        field._toggle(None)
        assert field._holder.visible is True
        field._toggle(None)
        assert field._holder.visible is False

    def test_picking_closes_it_again(self) -> None:
        """Leaving it open keeps the dialog at its tallest for nothing."""
        field = FormDateField(label="Next due date")
        field._toggle(None)
        field._picked(date(2026, 3, 9))
        assert field._holder.visible is False

    def test_the_open_calendar_starts_on_the_current_value(self) -> None:
        field = FormDateField(label="Next due date", value="2026-08-12")
        assert field._panel._selected == date(2026, 8, 12)

    def test_a_picked_date_lands_as_iso(self) -> None:
        field = FormDateField(label="Next due date")
        field._picked(date(2026, 3, 9))
        assert field.value == "2026-03-09"
        assert field._field.value == "Mar 9, 2026"


class TestBillDialogsUseIt:
    def test_no_typed_date_fields_remain(self) -> None:
        source = inspect.getsource(editor) + inspect.getsource(dialogs)
        assert "YYYY-MM-DD" not in source
        assert source.count("FormDateField(") == 3  # add + edit + pause
