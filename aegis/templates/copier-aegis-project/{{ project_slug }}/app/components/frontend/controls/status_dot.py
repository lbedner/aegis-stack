"""Themed status dot, bare and labelled.

A small filled circle in a design-system color, used in place of emoji
status indicators (green/red/blue/...) so status colors follow the theme
and can be recolored centrally (e.g. success is teal, not green).

``status_dot`` is the bare circle, for a table cell that has a column
header to say what it means. ``StatusDot`` adds the label beside it, for
everywhere else - a state riding inline in a row of prose needs its own
name.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme


def status_dot(color: str, size: int = 10) -> ft.Container:
    """Return a small filled status dot in ``color``.

    Args:
        color: Fill color (pass a ``Theme.Colors`` token).
        size: Diameter in pixels.

    Returns:
        A circular ``ft.Container`` filled with ``color``.
    """
    return ft.Container(
        width=size,
        height=size,
        bgcolor=color,
        border_radius=size / 2,
    )


class StatusDot(ft.Container):
    """A state as a dot plus its name: circle, label, both in one color.

    The house alternative to a bordered chip. A chip's outline gives it a
    box, and a box is what the dashboard's cards use to say "this is a
    thing in its own right" - a status is an ASIDE about something else,
    so it gets weight without chrome.

    Colour is the state, so the label wears it too: a grey word beside a
    red dot says two different things at once. A caller that wants the
    quiet form passes a muted color rather than dropping the dot, so the
    row keeps its shape whether or not anything is wrong.

    Args:
        label: What the state is called (e.g. "Detected", "50 scheduled").
        color: The state's color; pass a ``Theme.Colors`` token.
        tooltip: What the state MEANS. A bare word rarely says it, and
            this is the only place there is room to.
        size: Circle diameter. The default matches the dashboard's
            inline dots.
    """

    _DEFAULT_SIZE = 8

    def __init__(
        self,
        label: str,
        color: str,
        tooltip: str | None = None,
        size: int = _DEFAULT_SIZE,
    ) -> None:
        self.label = label
        self.color = color
        super().__init__(
            content=ft.Row(
                [
                    status_dot(color, size=size),
                    ft.Text(
                        label,
                        color=color,
                        size=Theme.Typography.BODY_SMALL,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            tooltip=tooltip,
        )
