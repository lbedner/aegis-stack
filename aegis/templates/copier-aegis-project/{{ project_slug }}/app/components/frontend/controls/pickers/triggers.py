"""What opens a picker: an inline cell, or a bulk-action button."""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend import styles
from app.components.frontend.controls.buttons import (
    PULSE_BUTTON_COMPACT_HEIGHT,
    PULSE_BUTTON_COMPACT_PADDING,
    PULSE_BUTTON_COMPACT_RADIUS,
)
from app.components.frontend.theme import AegisTheme as Theme


def picker_trigger_cell(
    content: ft.Control,
    width: int | None,
    *,
    on_tap: Callable[[ft.ControlEvent], None],
    tooltip: str | None = None,
) -> ft.Control:
    """The clickable shell a table cell opens a picker through - shared so
    two easy-to-miss fixes don't get re-derived (or drift) per call site:

    - An EXPLICIT ``width``, not ``expand=True``. There's no Row/Column
      ancestor in a plain DataTable cell for ``expand`` to mean anything
      against, and the outer cell Container's own ``alignment=`` (see
      ``build_cell``, controls/data_table.py) makes Flet shrink-wrap the
      child then position it, rather than stretch it - without an
      explicit width matching the column, the actual clickable area is
      just the content's own snug size, not the full column (confirmed
      live: reported as hard to hit).
    - A real ``on_click`` no-op alongside ``on_tap_down``. Only
      ``on_tap_down`` carries the tap coordinates ``open_for`` needs to
      position the popup (Dropdown._toggle's contract), but
      ``on_tap_down`` alone doesn't stop the tap from bubbling to the
      row's own ``on_click`` (DataTable's inline-expand toggle) the way a
      real ``on_click`` does - without this, tapping the cell ALSO
      opened/closed the row underneath the popup.

    ``width=None`` is for a WIDTH-LESS (flex) column, where there's no
    fixed number to claim: the trigger is wrapped in a Row so ``expand``
    finally has a flex parent to mean something against, which is the
    same recipe ``_pending_cell`` (finance_modal.py) already uses to keep
    its text from pushing its buttons off the column edge.
    """
    trigger = ft.Container(
        content=content,
        width=width,
        expand=width is None,
        ink=True,
        border_radius=Theme.Components.BUTTON_RADIUS,
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
        on_tap_down=on_tap,
        on_click=lambda _e: None,
        tooltip=tooltip,
    )
    if width is not None:
        return trigger
    return ft.Row([trigger], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)


class BulkActionTrigger(ft.Container):
    """ "<Label> (N)" chip: hidden while nothing's selected, opens the
    caller's shared picker for the CURRENT selection on tap. One class for
    every table that supports select-many-then-act (categorize on
    Uncategorized and the register, assign-payee on the register), so the
    styling and the on_tap_down/on_click-noop mechanics (see
    ``picker_trigger_cell``'s own docstring - the same reasoning applies
    here) exist in exactly one place rather than being hand-built per
    panel.
    """

    # This chip sits in the same header row as Add / Connect / Import, so it
    # has to read as one of them - but it can't BE a PulseButton: only
    # ``on_tap_down`` carries the tap coordinates ``open_for`` needs, and
    # ElevatedButton doesn't expose it. So it's a Container wearing the
    # button's look, taken FROM the button's own style rather than re-picked
    # by eye - including the hover states, which a Container has to drive
    # itself since it has no ControlState machinery.
    _STYLES = {
        "teal": styles.PULSE_BUTTON_TEAL_STYLE,
        # Destructive verbs (Dismiss, Delete) read red, matching
        # PulseButton's own "stop" variant.
        "stop": styles.PULSE_BUTTON_STOP_STYLE,
    }

    def _state(self, prop: str, state: ft.ControlState) -> Any:
        """One entry of the shared button style (its per-state props are
        ``{ControlState: value}`` maps; a few are plain values)."""
        value = getattr(self._style, prop)
        return value[state] if isinstance(value, dict) else value

    def __init__(
        self,
        on_tap: Callable[[ft.ControlEvent], None],
        *,
        label: str = "Categorize",
        tooltip: str = "Set the category for every checked row at once",
        variant: str = "teal",
    ) -> None:
        self._text = label
        self._style = self._STYLES[variant]
        self._idle_bg = self._state("bgcolor", ft.ControlState.DEFAULT)
        self._hover_bg = self._state("bgcolor", ft.ControlState.HOVERED)
        self._idle_fg = self._state("color", ft.ControlState.DEFAULT)
        self._hover_fg = self._state("color", ft.ControlState.HOVERED)
        side = self._state("side", ft.ControlState.DEFAULT)
        self._label = ft.Text(
            label,
            size=styles.PulseButtonTextStyle.size,
            weight=styles.PulseButtonTextStyle.weight,
            font_family=styles.PulseButtonTextStyle.font_family,
            color=self._idle_fg,
        )
        super().__init__(
            content=self._label,
            height=PULSE_BUTTON_COMPACT_HEIGHT,
            alignment=ft.alignment.center,
            border=ft.border.all(side.width, side.color),
            bgcolor=self._idle_bg,
            border_radius=PULSE_BUTTON_COMPACT_RADIUS,
            padding=PULSE_BUTTON_COMPACT_PADDING,
            ink=True,
            visible=False,
            on_tap_down=on_tap,
            on_click=lambda _e: None,
            on_hover=self._on_hover,
            tooltip=tooltip,
        )

    def _on_hover(self, e: ft.ControlEvent) -> None:
        hovering = e.data == "true"
        self.bgcolor = self._hover_bg if hovering else self._idle_bg
        self._label.color = self._hover_fg if hovering else self._idle_fg
        if self.page:
            self.update()

    def set_count(self, count: int) -> None:
        self._label.value = f"{self._text} ({count})" if count else self._text
        self.visible = bool(count)
        if self.page:
            self.update()
