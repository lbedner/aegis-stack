"""Reusable action menus: the data-table kebab (``ActionMenu``) and the
Pulse-styled dropdown pill (``ActionDropdown``).

``ActionMenu``/``ActionMenuItem`` wrap Flet's native ``PopupMenuButton``,
which is right inside a data table (a row kebab is Material chrome
anyway) but wrong anywhere the Pulse look is the standard: its popup
surface takes no border, no Pulse surface token, and Material's own
type scale and row spacing - visibly a different design language sitting
next to Pulse controls. ``ActionDropdown`` is the Pulse answer, built on
``Dropdown``'s overlay panel, which can carry all three.

Theme-aware either way: icon and label colors come from Material
semantic tokens (``ft.Colors.ON_SURFACE`` / ``ON_SURFACE_VARIANT`` /
``ERROR``) so they adapt with light/dark mode.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from app.components.frontend.controls.dropdown import Dropdown
from app.components.frontend.controls.text import (
    ErrorText,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.styles import PulseColors
from app.components.frontend.theme import AegisTheme as Theme


class ActionMenuItem(ft.PopupMenuItem):
    """A row-action menu item with icon + label.

    Pass ``destructive=True`` to render in the error palette (red icon
    and label) for delete-style actions.
    """

    def __init__(
        self,
        label: str,
        icon: str,
        on_click: Callable[[ft.ControlEvent], None],
        *,
        destructive: bool = False,
    ) -> None:
        icon_color = ft.Colors.ERROR if destructive else ft.Colors.ON_SURFACE_VARIANT
        text_color = ft.Colors.ERROR if destructive else ft.Colors.ON_SURFACE
        super().__init__(
            content=ft.Row(
                [
                    ft.Icon(icon, color=icon_color, size=18),
                    ft.Text(label, color=text_color),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=on_click,
        )


class ActionMenu(ft.PopupMenuButton):
    """Kebab-style row-action menu button.

    Composes a ``MORE_HORIZ`` icon trigger with the supplied items.
    Use ``ft.PopupMenuItem()`` (no args) inside ``items`` to insert a
    divider between groups.
    """

    def __init__(self, items: list[ft.PopupMenuItem]) -> None:
        super().__init__(
            icon=ft.Icons.MORE_HORIZ,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            tooltip="Actions",
            items=items,
        )


@dataclass(frozen=True)
class MenuAction:
    """One row in an ``ActionDropdown`` panel.

    ``caption`` is a second, muted line under the label - use it when the
    choice needs a qualifier to be made confidently (what file formats an
    import accepts, say) rather than as decoration.
    """

    label: str
    icon: str
    on_click: Callable[[ft.ControlEvent], None]
    caption: str | None = None
    destructive: bool = False


def _menu_action_row(action: MenuAction, on_chosen: Callable[[], None]) -> ft.Container:
    """One Pulse panel row: icon, label, optional caption.

    ``ink=True`` for the press ripple a native ``PopupMenuItem`` gets for
    free - inside ``Dropdown``'s own panel these are plain rows, so it
    has to be asked for. Picking a row closes the panel (via
    ``on_chosen``): unlike the multi-select account filter, these are
    one-shot commands.
    """
    icon_color = ft.Colors.ERROR if action.destructive else ft.Colors.ON_SURFACE_VARIANT
    # The text controls carry their own semantic colour - ErrorText IS the
    # red one - so neither needs a colour passed in here.
    label: ft.Control = (
        ErrorText(action.label, size=Theme.Typography.BODY_SMALL)
        if action.destructive
        else PrimaryText(action.label, size=Theme.Typography.BODY_SMALL)
    )
    if action.caption:
        label = ft.Column(
            [label, SecondaryText(action.caption, size=Theme.Typography.CAPTION)],
            spacing=1,
            tight=True,
        )

    def _click(event: ft.ControlEvent) -> None:
        on_chosen()
        action.on_click(event)

    return ft.Container(
        content=ft.Row(
            [ft.Icon(action.icon, size=16, color=icon_color), label],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        on_click=_click,
        ink=True,
        border_radius=Theme.Components.BUTTON_RADIUS,
        padding=ft.padding.symmetric(
            vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
        ),
    )


class ActionDropdown(Dropdown):
    """A Pulse pill trigger that opens a bordered panel of actions.

    The Pulse-styled alternative to a native ``PopupMenuButton`` menu:
    same job, but the panel is ``Dropdown``'s overlay frame, so it
    carries the app's border, surface, radius, shadow and type scale
    instead of Material's defaults.

    The trigger is the house pill (translucent teal fill, 1px teal
    border, 28px line box), sized to sit in a row beside a compact
    ``PulseButton``. It brings its own chrome, so the frame's trigger
    padding is zeroed - see ``Dropdown``'s ``trigger_padding``.
    """

    _PILL_HEIGHT = 28
    # No live-measure API in Flet, so the pill's width is estimated from
    # its label: ~7px per character at BODY_SMALL, plus the arrow glyph
    # and the pill's own horizontal padding. Only used to anchor the
    # panel under the trigger, so being a few px out is invisible.
    _CHAR_WIDTH = 7
    _PILL_CHROME = 32

    def __init__(
        self,
        label: str,
        actions: list[MenuAction],
        *,
        tooltip: str = "",
        align: str = "left",
        min_width: int = 260,
    ) -> None:
        teal = PulseColors.TEAL
        pill = ft.Container(
            content=ft.Row(
                [
                    PrimaryText(
                        label,
                        size=Theme.Typography.BODY_SMALL,
                        color=PulseColors.TEXT,
                        weight=ft.FontWeight.W_500,
                    ),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=PulseColors.TEXT),
                ],
                spacing=2,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=self._PILL_HEIGHT,
            padding=ft.padding.only(left=10, right=4),
            bgcolor=ft.Colors.with_opacity(0.10, teal),
            border=ft.border.all(1, teal),
            border_radius=6,
            alignment=ft.alignment.center,
            tooltip=tooltip or None,
        )
        super().__init__(
            trigger=pill,
            panel=ft.Column(
                [_menu_action_row(action, self.close) for action in actions],
                spacing=0,
                tight=True,
            ),
            align=align,
            trigger_width=len(label) * self._CHAR_WIDTH + self._PILL_CHROME,
            trigger_height=self._PILL_HEIGHT,
            trigger_padding=ft.padding.all(0),
            min_width=min_width,
            # Hug the rows: a fixed height would strand two or three
            # actions in a tall, mostly empty box.
            max_height=None,
        )
