"""The clear (x) affordance on search fields.

A search box with no way out makes you select-all-delete to see the
unfiltered list again - and on these tabs a stale query is invisible from
the results alone: an empty table reads as "nothing here" whether the
filter is wrong or the data really is empty. Confirmed on Bills & Income,
where "cap" at the default range showed Detected (0) for a bill that
existed.
"""

import flet as ft

from app.components.frontend.controls.form_fields import FormTextField


class TestClearable:
    def test_off_by_default(self) -> None:
        """Not every field wants it - a name or an amount is typed once,
        not narrowed repeatedly."""
        field = FormTextField(label="Payee name")
        assert field._clear_button is None

    def test_the_input_is_decorated_exactly_like_a_plain_one(self) -> None:
        """THE invariant. Put the button in the TextField's ``suffix``
        slot and it becomes part of the input's decoration: its 24px box
        sets the content row height and the typed text sits low - forever,
        not just while toggling. Overlaying keeps the input measuring
        itself as if the button were not there.
        """
        plain = FormTextField(label="Payee name")
        clearable = FormTextField(label="Search payee", clearable=True)
        assert clearable._text_field.suffix is None
        assert clearable._text_field.suffix == plain._text_field.suffix
        assert clearable._text_field.height == plain._text_field.height

    def test_the_text_cannot_slide_under_the_button(self) -> None:
        """The overlay sits ON the field, so the input has to reserve the
        gutter itself."""
        plain = FormTextField(label="Payee name")
        clearable = FormTextField(label="Search payee", clearable=True)
        assert (
            clearable._text_field.content_padding.right
            > plain._text_field.content_padding.right
        )

    def test_hidden_while_empty(self) -> None:
        field = FormTextField(label="Search payee", clearable=True)
        assert field._clear_button is not None
        assert field._clear_icon.opacity == 0.0

    def test_shown_once_there_is_something_to_clear(self) -> None:
        field = FormTextField(label="Search payee", value="cap", clearable=True)
        assert field._clear_icon.opacity == 1.0

    def test_the_slot_never_moves(self) -> None:
        """The glyph fades; the slot does not come and go. Toggling the
        suffix's own ``visible`` re-lays-out the input's content row, so
        the typed text jumped on the first keystroke and again on the
        last delete. Reported live, twice."""
        field = FormTextField(label="Search payee", clearable=True)
        slot = field._clear_button
        before = (slot.visible, slot.width, slot.right)
        field._text_field.value = "cap"
        field._sync_clear_button()
        assert (slot.visible, slot.width, slot.right) == before
        field._clear(None)
        assert (slot.visible, slot.width, slot.right) == before

    def test_clicking_it_while_empty_does_nothing(self) -> None:
        """The hit target is always mounted so the layout holds still, but
        an invisible glyph must not be clickable."""
        seen: list[str] = []
        field = FormTextField(
            label="Search payee",
            clearable=True,
            on_change=lambda e: seen.append(e.control.value or ""),
        )
        field._clear(None)
        assert seen == []

    def test_typing_reveals_it(self) -> None:
        field = FormTextField(label="Search payee", clearable=True)
        field._text_field.value = "cap"
        field._handle_change(
            ft.ControlEvent(
                target="",
                name="change",
                data="cap",
                control=field._text_field,
                page=None,
            )
        )
        assert field._clear_icon.opacity == 1.0

    def test_clearing_empties_the_field(self) -> None:
        field = FormTextField(label="Search payee", value="cap", clearable=True)
        field._clear(None)
        assert field.value == ""
        assert field._clear_icon.opacity == 0.0

    def test_clearing_notifies_the_owner(self) -> None:
        """The panel re-filters off on_change, so a clear that does not
        fire it empties the box and leaves the results filtered."""
        seen: list[str] = []
        field = FormTextField(
            label="Search payee",
            value="cap",
            clearable=True,
            on_change=lambda e: seen.append(e.control.value or ""),
        )
        field._clear(None)
        assert seen == [""]

    def test_it_never_drives_the_input_height(self) -> None:
        """A stock IconButton brings Material's ~48px hit box - taller than
        the input (40, or 36 compact). As a suffix that grows the content
        row and pushes the typed text off centre, which is what it did.
        """
        from app.components.frontend.controls.form_fields import _CLEAR_HIT_SIZE

        for compact, box in ((False, 40), (True, 36)):
            field = FormTextField(
                label="Search payee", value="chosen", clearable=True, compact=compact
            )
            assert field._clear_button.width == _CLEAR_HIT_SIZE
            assert _CLEAR_HIT_SIZE < box, f"clear button too tall for compact={compact}"

    def test_it_is_not_an_icon_button(self) -> None:
        """The Material geometry is the whole problem - a plain Container
        keeps the click target without it."""
        field = FormTextField(label="Search payee", clearable=True)
        assert not isinstance(field._clear_button, ft.IconButton)
        assert field._clear_button.on_click is not None


class TestStyledTextField:
    """The bare house input as a CONTROL: one class every inline text
    field uses, instead of each surface passing the kwargs recipe into
    a raw ft.TextField."""

    def test_wears_the_house_recipe(self) -> None:
        from app.components.frontend.controls.form_fields import input_field_kwargs
        from app.components.frontend.controls.inputs import StyledTextField

        field = StyledTextField(hint_text="Search models")
        recipe = input_field_kwargs("default", None)
        assert field.bgcolor == recipe["bgcolor"]
        assert field.border_color == recipe["border_color"]
        assert field.hint_text == "Search models"

    def test_compact_pins_the_toolbar_height(self) -> None:
        from app.components.frontend.controls.inputs import StyledTextField

        assert StyledTextField(compact=True).height == 36

    def test_call_site_overrides_win(self) -> None:
        from app.components.frontend.controls.inputs import StyledTextField

        field = StyledTextField(text_size=15)
        assert field.text_size == 15
