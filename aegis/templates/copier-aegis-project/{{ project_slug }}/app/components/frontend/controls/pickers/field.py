"""A category picker that sits in a form rather than a popup."""

import flet as ft

from app.components.frontend.controls.buttons import (
    PulseButton,
)
from app.components.frontend.controls.dialog import DialogHandle, StyledAlertDialog
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.pickers.search import _filter_options, _option_row
from app.components.frontend.theme import AegisTheme as Theme


class CategoryPickerField(ft.Container):
    """FormDropdown-shaped category field that opens the searchable list
    in a NESTED dialog.

    A flat ``ft.Dropdown`` stops working at a few hundred categories - no
    search, one endless scroll (confirmed live from the Make recurring
    dialog). The obvious replacement - anchoring ``CategoryPickerButton``'s
    floating panel from the field - cannot work where this field lives:
    an open ``AlertDialog`` sits on its own route ABOVE everything in
    ``page.overlay``, so the panel rendered underneath the form dialog
    (confirmed live too, peeking out below it). Dialog routes stack in
    open order, so the search panel opens as a small second dialog
    instead; picking (or Cancel) drops back to the form.

    Drop-in for the ``FormDropdown`` call sites it replaces: ``value``
    holds the picked key as a string, ``""`` meaning the empty choice
    (``empty_label``, e.g. "Infer from transactions").
    """

    _ROWS_HEIGHT = 400  # explicit, so the inner scroll column actually scrolls

    def __init__(
        self,
        *,
        categories: list[tuple[str, str]],
        label: str = "Category",
        value: str = "",
        width: int | None = None,
        empty_label: str = "Infer from transactions",
    ) -> None:
        super().__init__()
        self.width = width
        self._label = label
        self._options: list[tuple[str, str]] = [("", empty_label), *categories]
        self._labels: dict[str, str] = dict(self._options)
        self._value = value if value in self._labels else ""
        self._display = ft.Text(
            self._labels[self._value],
            size=13,
            color=(Theme.Colors.TEXT_SECONDARY if not self._value else None),
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
            expand=True,
        )
        trigger = ft.Container(
            content=ft.Row(
                [
                    self._display,
                    ft.Icon(
                        ft.Icons.ARROW_DROP_DOWN,
                        size=20,
                        color=ft.Colors.OUTLINE,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            ink=True,
            on_click=self._open,
        )
        from app.components.frontend.controls.form_fields import _build_label

        self.content = ft.Column(
            [_build_label(label, "default"), ft.Container(height=4), trigger],
            spacing=0,
            tight=True,
        )

    def _open(self, _e: ft.ControlEvent) -> None:
        if self.page is None:
            return
        page = self.page
        rows_column = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
        dialog_handle = DialogHandle()

        def _close() -> None:
            dialog_handle.close(page)

        def _pick(key: str) -> None:
            self.value = key
            _close()

        def _render(query: str) -> None:
            matches = _filter_options(self._options, query)
            rows: list[ft.Control] = [
                _option_row(text, lambda _e, k=key: _pick(k), ft.Colors.ON_SURFACE)
                for key, text in matches
            ]
            if not rows:
                rows = [
                    ft.Container(
                        content=ft.Text(
                            "No matches",
                            size=13,
                            color=Theme.Colors.TEXT_SECONDARY,
                        ),
                        padding=ft.padding.symmetric(
                            vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
                        ),
                    )
                ]
            rows_column.controls = rows
            if rows_column.page is not None:
                rows_column.update()

        search = FormTextField(
            label="",
            hint="Search categories",
            show_label=False,
            compact=True,
            autofocus=True,
            on_change=lambda e: _render(e.control.value or ""),
        )
        _render("")

        async def _cancel() -> None:
            _close()

        dialog = StyledAlertDialog(
            handle=dialog_handle,
            title=self._label,
            body=ft.Column(
                [
                    search,
                    ft.Divider(height=1, color=Theme.Colors.BORDER_SUBTLE),
                    ft.Container(content=rows_column, height=self._ROWS_HEIGHT),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                )
            ],
            width=420,
        )
        page.open(dialog)

    @property
    def value(self) -> str:
        return self._value

    @value.setter
    def value(self, new_value: str) -> None:
        self._value = new_value if new_value in self._labels else ""
        self._display.value = self._labels[self._value]
        self._display.color = Theme.Colors.TEXT_SECONDARY if not self._value else None
        if self.page:
            self._display.update()
