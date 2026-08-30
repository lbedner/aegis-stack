"""The active-model picker dialog: chips, grouped tiles, newest first.

Visual shape follows the house catalog treatment: filter chips
(Vendors / Families / All), an ExpansionTile per group with the vendor's
real brand icon (server-resolved, same machinery as payee icons; a
colored initial fills in until the icon lands), and model rows that
activate on click via ``POST /api/v1/llm/current``. The list is
key-gated upstream: vendors this install cannot call never appear.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.text import (
    LabelText,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from .models import group_models, model_label, newest_first

_GROUP_MODES = (("vendor", "Vendors"), ("family", "Families"), ("all", "All"))


def _initial_avatar(name: str, color: str | None, radius: int = 10) -> ft.Control:
    """A colored initial standing in for a vendor/model logo."""
    return ft.CircleAvatar(
        max_radius=radius,
        bgcolor=color or Theme.Colors.SURFACE_1,
        content=ft.Text(
            (name or "?")[:1].upper(),
            size=radius + 1,
            weight=ft.FontWeight.W_600,
            color=Theme.Colors.TEXT_PRIMARY,
        ),
    )


def _avatar(
    name: str,
    color: str | None,
    icon_b64: str | None,
    radius: int = 10,
) -> ft.Control:
    """The vendor's brand icon when resolved, the colored initial until
    then - the same degrade path payee icons ride."""
    if icon_b64:
        return ProviderIcon(name, icon_b64)
    return _initial_avatar(name, color, radius)


class ModelPickerDialog(StyledAlertDialog):
    """Pick the globally active model from the real catalog."""

    def __init__(
        self,
        *,
        models: list[dict[str, Any]],
        active_id: str,
        on_pick: Callable[[str], Awaitable[None]],
        on_close: Callable[[], Awaitable[None]],
        vendor_icons: dict[str, str] | None = None,
    ) -> None:
        self._models = models
        self._active_id = active_id
        self._vendor_icons = vendor_icons or {}
        self._on_pick = on_pick
        self._mode = "vendor"
        self._chips: dict[str, ft.Container] = {}
        self._list_host = ft.Container(
            content=self._build_list(), height=380, width=460
        )
        chips_row = ft.Row(
            [self._build_chip(mode, label) for mode, label in _GROUP_MODES],
            spacing=Theme.Spacing.XS,
        )
        super().__init__(
            title="Active model",
            body=ft.Column(
                [chips_row, self._list_host], spacing=Theme.Spacing.SM, tight=True
            ),
            width=520,
            on_close=on_close,
        )

    # -- chips -------------------------------------------------------------

    def _build_chip(self, mode: str, label: str) -> ft.Container:
        selected = mode == self._mode
        chip = ft.Container(
            content=SecondaryText(
                label, size=Theme.Typography.BODY_SMALL, selectable=False
            ),
            bgcolor=(
                ft.Colors.with_opacity(0.25, Theme.Colors.ACCENT)
                if selected
                else Theme.Colors.SURFACE_1
            ),
            border_radius=12,
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.XS
            ),
            ink=True,
            on_click=lambda _event, m=mode: self._switch_mode(m),
        )
        self._chips[mode] = chip
        return chip

    def _switch_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        for chip_mode, chip in self._chips.items():
            chip.bgcolor = (
                ft.Colors.with_opacity(0.25, Theme.Colors.ACCENT)
                if chip_mode == mode
                else Theme.Colors.SURFACE_1
            )
        self._list_host.content = self._build_list()
        if self.page:
            self.page.update()

    # -- lists -------------------------------------------------------------

    def _build_list(self) -> ft.Control:
        if self._mode == "all":
            rows: list[ft.Control] = [
                self._model_row(model) for model in newest_first(self._models)
            ]
        else:
            rows = []
            for name, group in group_models(self._models, by=self._mode):
                rows.append(self._group_tile(name, group))
        if not rows:
            rows = [SecondaryText("No models in the catalog yet.")]
        return ft.ListView(rows, spacing=2, padding=0)

    def _group_tile(self, name: str, group: list[dict[str, Any]]) -> ft.Control:
        color = next((m.get("color") for m in group if m.get("color")), None)
        # A family/all group still belongs to one vendor in practice;
        # its first row names the icon to wear.
        vendor = name if self._mode == "vendor" else group[0].get("vendor", "")
        return ft.ExpansionTile(
            title=ft.Row(
                [
                    _avatar(name, color, self._vendor_icons.get(vendor), radius=12),
                    PrimaryText(name, selectable=False),
                    LabelText(str(len(group)), selectable=False),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            controls=[
                ft.Column(
                    [self._model_row(model) for model in group], tight=True, spacing=2
                )
            ],
            dense=True,
            initially_expanded=any(
                model.get("model_id") == self._active_id for model in group
            ),
        )

    def _model_row(self, model: dict[str, Any]) -> ft.Control:
        model_id = str(model.get("model_id", ""))
        title = str(model.get("title") or model_id)
        return ft.Container(
            content=ft.Row(
                [
                    _avatar(
                        title,
                        model.get("color"),
                        self._vendor_icons.get(str(model.get("vendor", ""))),
                    ),
                    ft.Column(
                        [
                            PrimaryText(title, no_wrap=True, selectable=False),
                            SecondaryText(
                                model_id,
                                size=Theme.Typography.BODY_SMALL,
                                no_wrap=True,
                                selectable=False,
                            ),
                        ],
                        spacing=0,
                        tight=True,
                        expand=True,
                    ),
                    ft.Icon(
                        ft.Icons.CHECK,
                        size=16,
                        color=Theme.Colors.ACCENT,
                        visible=model_id == self._active_id,
                    ),
                ],
                spacing=Theme.Spacing.SM,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.XS
            ),
            border_radius=Theme.Components.BUTTON_RADIUS,
            ink=True,
            on_click=lambda _event, mid=model_id: self.page.run_task(
                self._on_pick, mid
            ),
        )


class ModelChipMixin:
    """The panel's model chip + picker verbs.

    State contract with ``ChatPanel``: ``_api()``, ``_model_chip_label``,
    ``_model_dialog``, ``page``. Split from the panel purely so each
    module stays inside the size budget - one surface, two files.
    """

    async def _refresh_model_chip(self) -> None:
        current = await self._api().get("/api/v1/llm/current")
        self._model_chip_label.value = model_label(current)
        if self.page:
            self._model_chip_label.update()

    async def _pick_model(self, model_id: str) -> None:
        result = await self._api().post("/api/v1/llm/current", {"model_id": model_id})
        if not result or not result.get("success"):
            from app.components.frontend.controls.snack_bar import ErrorSnackBar

            detail = (result or {}).get("message") or "Model switch failed."
            self.page.open(ErrorSnackBar(detail))
            return
        if self._model_dialog is not None:
            self._model_dialog.open = False
        await self._refresh_model_chip()
        self.page.update()

    async def _close_model_picker(self) -> None:
        if self._model_dialog is not None:
            self._model_dialog.open = False
            self.page.update()

    async def _open_model_picker(self) -> None:
        models = await self._api().get(
            "/api/v1/llm/models", {"limit": 200, "usable": True}
        )
        vendors = await self._api().get("/api/v1/llm/vendors", {"usable": True})
        current = await self._api().get("/api/v1/llm/current")
        vendor_icons = {
            v["name"]: v["icon_b64"] for v in (vendors or []) if v.get("icon_b64")
        }
        self._model_dialog = ModelPickerDialog(
            models=models or [],
            vendor_icons=vendor_icons,
            active_id=str((current or {}).get("model") or ""),
            on_pick=self._pick_model,
            on_close=self._close_model_picker,
        )
        self.page.open(self._model_dialog)
