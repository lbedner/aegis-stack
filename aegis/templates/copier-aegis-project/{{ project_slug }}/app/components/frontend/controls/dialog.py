"""House-standard dialog shell.

Flet's ``AlertDialog`` cannot draw a border (``RoundedRectangleBorder``
carries no ``side``), so the standard dialog surface - the
``SURFACE_CONTAINER_HIGHEST`` panel with a 1px ``OUTLINE`` edge and
``CARD_RADIUS`` corners that ``BaseDetailPopup`` uses - is painted by a
Container INSIDE a chromeless dialog: the ``AlertDialog`` itself is
transparent and paddingless, and title, body, and action row all live on
the bordered panel.
"""

from collections.abc import Awaitable, Callable
import inspect

import flet as ft

from app.components.frontend.controls.text import H3Text
from app.components.frontend.theme import AegisTheme as Theme


class StyledAlertDialog(ft.AlertDialog):
    """The house dialog: bordered panel, title, body, right-aligned actions.

    Callers provide the body control and ready-made action buttons
    (compact ``PulseButton``s by convention) and keep using the normal
    ``page.open(dialog)`` / ``dialog.open = False`` lifecycle.
    """

    def __init__(
        self,
        *,
        title: str,
        body: ft.Control,
        actions: list[ft.Control] | None = None,
        width: int = 360,
        on_close: Callable[[], Awaitable[None] | None] | None = None,
        accent_color: str | None = None,
        modal: bool = True,
    ) -> None:
        """
        Args:
            on_close: Puts a small × in the title row instead of (or
                alongside) the bottom action row - for a dialog that's
                read-only or whose only "action" is dismissing it, a
                footer-anchored Close button reads as an odd, separate
                decision rather than the obvious way out (RecordDetailDialog's
                own fix for exactly this). Leaves ``actions`` alone, so a
                dialog that also has real actions (Save, Delete) can use
                both - × to bail, the footer for committing something.
            accent_color: A 2px tinted bar along the panel's top edge,
                rounded to match its corners - a plain 1px OUTLINE border
                on a SURFACE_CONTAINER_HIGHEST panel reads flat against
                the page's near-black background otherwise. Omit for the
                house default (no accent).
        """
        title_row: ft.Control = H3Text(title)
        if on_close is not None:

            async def _handle_close(_e: ft.ControlEvent) -> None:
                # on_close (RecordDetailDialog's own ``_close``, typically)
                # is often an async bound method - calling it from a plain
                # sync on_click just builds a coroutine and drops it on the
                # floor without ever running (confirmed live: the × did
                # nothing). Await it when it returns one; a plain sync
                # on_close still works unchanged.
                result = on_close()
                if inspect.isawaitable(result):
                    await result

            title_row = ft.Row(
                [
                    H3Text(title),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=18,
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        tooltip="Close",
                        on_click=_handle_close,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        column_children: list[ft.Control] = [title_row, body]
        if actions:
            column_children.append(
                ft.Row(
                    actions,
                    alignment=ft.MainAxisAlignment.END,
                    spacing=Theme.Spacing.SM,
                )
            )
        padded_content = ft.Container(
            content=ft.Column(column_children, spacing=Theme.Spacing.MD, tight=True),
            padding=20,
        )
        # The accent bar sits OUTSIDE the padded content, full-bleed to the
        # panel's own edges, in an unpadded outer Container - a bar sized
        # to the INNER (padded) width would float 20px short of the
        # panel's real corners on each side instead of tracing them.
        # ``clip_behavior=HARD_EDGE`` on that outer Container is what
        # squares the bar's own corners off to the panel's rounded ones,
        # instead of needing to round the bar itself to match by hand.
        panel_content: ft.Control = (
            ft.Column(
                [ft.Container(height=2, bgcolor=accent_color), padded_content],
                spacing=0,
                tight=True,
            )
            if accent_color is not None
            else padded_content
        )
        panel = ft.Container(
            content=panel_content,
            width=width,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )
        super().__init__(
            # ``modal=False`` lets a click on the barrier dismiss - right
            # for browse-and-leave dialogs like the model picker.
            modal=modal,
            # Text controls are plain (see controls/text.py): selection is a
            # property of the region, so every surface encloses its own.
            content=ft.SelectionArea(content=panel),
            content_padding=0,
            bgcolor=ft.Colors.TRANSPARENT,
            elevation=0,
        )
