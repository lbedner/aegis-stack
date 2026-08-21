"""The status dot, in its two forms.

``status_dot()`` is the bare circle - a cell marker, no words. ``StatusDot``
is the labelled form: the same circle with its meaning spelled out beside
it, which is what the dashboard actually shows wherever a state needs
naming (Bills & Income's streams, the Budget tab's Fixed / Non-monthly
rows, an import's scheduled and errored counts).

The labelled form is a CONTROL rather than a helper returning a bare
Container on purpose: a caller that wants "the house dot" should be able
to reach for a name, and anything checking that a surface uses it should
be able to ask, instead of recognising a circle by its pixel size.
"""

import flet as ft
from app.components.frontend.controls import StatusDot, status_dot
from app.components.frontend.dashboard.modals import modal_sections
from app.components.frontend.theme import AegisTheme as Theme


class TestBareDot:
    def test_it_is_a_circle_of_the_given_size(self) -> None:
        dot = status_dot(Theme.Colors.SUCCESS, size=12)
        assert (dot.width, dot.height) == (12, 12)
        assert dot.border_radius == 6
        assert dot.bgcolor == Theme.Colors.SUCCESS


class TestLabelledDot:
    def test_the_label_and_the_dot_share_one_colour(self) -> None:
        """The colour IS the state; a grey word beside a red dot says two
        different things at once."""
        dot = StatusDot("2 errors", Theme.Colors.ERROR, "Could not be placed.")
        assert dot.label == "2 errors"
        assert dot.color == Theme.Colors.ERROR
        assert dot.tooltip == "Could not be placed."

    def test_it_reuses_the_bare_dot_recipe(self) -> None:
        """One circle recipe, so a change to it lands everywhere at once."""
        dot = StatusDot("50 scheduled", Theme.Colors.WARNING, "Not yet posted.")
        circle = dot.content.controls[0]
        assert circle.width == circle.height
        assert circle.border_radius == circle.width / 2
        assert circle.bgcolor == Theme.Colors.WARNING

    def test_the_label_is_rendered(self) -> None:
        dot = StatusDot("50 scheduled", Theme.Colors.WARNING, "Not yet posted.")
        text = dot.content.controls[1]
        assert isinstance(text, ft.Text)
        assert text.value == "50 scheduled"
        assert text.color == Theme.Colors.WARNING


class TestOneControlEverywhere:
    def test_the_modal_sections_helper_returns_the_control(self) -> None:
        """The finance tabs call the helper, the import dialog calls the
        control. They have to be the same thing, or "the house dot" is
        two recipes that drift."""
        built = modal_sections.status_dot("Detected", Theme.Colors.INFO, "A guess.")
        assert isinstance(built, StatusDot)
        assert built.label == "Detected"
