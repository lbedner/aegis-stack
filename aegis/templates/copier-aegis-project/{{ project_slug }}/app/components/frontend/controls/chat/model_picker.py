"""The active-model picker dialog, executive treatment.

Monochrome-first: thin borders, small-caps section headers, muted data
columns (context window, per-million pricing), and teal reserved for
exactly one meaning - the active model. Sections build their rows
LAZILY on first expand (the recurring tab's lesson: hundreds of rows
of controls serialized over the websocket is what "slow" is), search
filters the already-fetched catalog client-side, and visible row
counts are capped honestly with a "showing N of M" line rather than a
silent truncation.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.text import (
    LabelText,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from .models import (
    display_title,
    filter_models,
    format_context_window,
    format_price,
    group_models,
    lab_for_model,
    model_label,
    newest_first,
)

_GROUP_MODES = (("vendor", "Vendors"), ("family", "Families"), ("all", "All"))
# Rows built per section / per flat list before the "search to narrow"
# line takes over. The cap is a serialization budget, not a data limit:
# search reaches everything.
_SECTION_ROW_CAP = 30
_FLAT_ROW_CAP = 60


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


class _LazySection(ft.Column):  # type: ignore[misc]
    """A collapsible group whose rows are built on FIRST expand only.

    The header always exists; the body is a placeholder until opened.
    Collapsed sections therefore cost one row of controls, not their
    whole catalog.
    """

    def __init__(
        self,
        *,
        header: ft.Control,
        build_rows: Callable[[], list[ft.Control]],
        expanded: bool,
    ) -> None:
        self._build_rows = build_rows
        self._built = False
        self._chevron = ft.Icon(
            ft.Icons.EXPAND_MORE,
            size=16,
            color=Theme.Colors.TEXT_SECONDARY,
        )
        self._body = ft.Column(tight=True, spacing=4, visible=False)
        head = ft.Container(
            content=ft.Row(
                [ft.Container(header, expand=True), self._chevron],
                spacing=Theme.Spacing.XS,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.SM
            ),
            border=ft.border.only(bottom=ft.BorderSide(1, Theme.Colors.BORDER_SUBTLE)),
            ink=True,
            on_click=self._toggle,
        )
        super().__init__([head, self._body], tight=True, spacing=0)
        if expanded:
            self._expand()

    def _expand(self) -> None:
        if not self._built:
            self._body.controls = self._build_rows()
            self._built = True
        self._body.visible = True
        self._chevron.name = ft.Icons.EXPAND_LESS

    def _toggle(self, _event: ft.ControlEvent) -> None:
        if self._body.visible:
            self._body.visible = False
            self._chevron.name = ft.Icons.EXPAND_MORE
        else:
            self._expand()
        if self.page:
            self.update()


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
        self._query = ""
        self._chips: dict[str, ft.Container] = {}
        self._search = StyledTextField(
            hint_text="Search models",
            compact=True,
            on_change=self._on_search,
        )
        self._list_host = ft.Container(
            content=self._build_list(), height=380, width=460
        )
        chips_row = ft.Row(
            [self._build_chip(mode, label) for mode, label in _GROUP_MODES],
            spacing=Theme.Spacing.SM,
        )
        super().__init__(
            title="Active model",
            body=ft.Column(
                [self._search, chips_row, self._list_host],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            width=520,
            on_close=on_close,
            modal=False,
        )

    def set_active(self, model_id: str) -> None:
        """Reflect a pick IN PLACE - the dialog stays up, so comparing
        and switching twice costs no reopen."""
        self._active_id = model_id
        self._refresh_list()

    # -- chips -------------------------------------------------------------

    def _build_chip(self, mode: str, label: str) -> ft.Container:
        chip = ft.Container(
            content=SecondaryText(
                label, size=Theme.Typography.BODY_SMALL, selectable=False
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.XS, vertical=Theme.Spacing.XS
            ),
            ink=True,
            on_click=lambda _event, m=mode: self._switch_mode(m),
        )
        self._chips[mode] = chip
        self._style_chip(mode)
        return chip

    def _style_chip(self, mode: str) -> None:
        """Selected reads as text emphasis plus a hairline underline -
        monochrome, no filled pills; teal stays the active model's."""
        chip = self._chips[mode]
        selected = mode == self._mode
        text = chip.content
        if isinstance(text, ft.Text):
            text.color = (
                Theme.Colors.TEXT_PRIMARY if selected else Theme.Colors.TEXT_SECONDARY
            )
            text.weight = ft.FontWeight.W_600 if selected else ft.FontWeight.W_400
        chip.border = ft.border.only(
            bottom=ft.BorderSide(
                2,
                Theme.Colors.TEXT_PRIMARY if selected else ft.Colors.TRANSPARENT,
            )
        )

    def _switch_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        for chip_mode in self._chips:
            self._style_chip(chip_mode)
        self._refresh_list()

    def _on_search(self, event: ft.ControlEvent) -> None:
        self._query = str(event.control.value or "")
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list_host.content = self._build_list()
        if self.page:
            self.page.update()

    # -- lists -------------------------------------------------------------

    def _build_list(self) -> ft.Control:
        if self._query.strip():
            matches = newest_first(filter_models(self._models, self._query))
            rows = self._flat_rows(matches, cap=_FLAT_ROW_CAP)
        elif self._mode == "all":
            rows = self._flat_rows(newest_first(self._models), cap=_FLAT_ROW_CAP)
        else:
            rows = [
                self._section(name, group)
                for name, group in group_models(self._models, by=self._mode)
            ]
        if not rows:
            rows = [SecondaryText("No models match.")]
        return ft.ListView(
            rows, spacing=Theme.Spacing.XS, padding=ft.padding.only(top=2, bottom=8)
        )

    def _flat_rows(
        self,
        models: list[dict[str, Any]],
        *,
        cap: int,
        under_vendor: str | None = None,
    ) -> list[ft.Control]:
        rows: list[ft.Control] = [
            self._model_row(m, under_vendor=under_vendor) for m in models[:cap]
        ]
        if len(models) > cap:
            rows.append(self._more_line(len(models) - cap))
        return rows

    def _more_line(self, hidden: int) -> ft.Control:
        return ft.Container(
            content=SecondaryText(
                f"{hidden} more - search to narrow",
                size=Theme.Typography.BODY_SMALL,
                selectable=False,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.XS
            ),
        )

    def _section(self, name: str, group: list[dict[str, Any]]) -> ft.Control:
        color = next((m.get("color") for m in group if m.get("color")), None)
        # A family/all group still belongs to one vendor in practice;
        # its first row names the icon to wear.
        vendor = name if self._mode == "vendor" else group[0].get("vendor", "")
        header = ft.Row(
            [
                _avatar(name, color, self._vendor_icons.get(vendor), radius=9),
                LabelText(name.upper(), selectable=False),
                SecondaryText(
                    str(len(group)),
                    size=Theme.Typography.BODY_SMALL,
                    selectable=False,
                ),
            ],
            spacing=Theme.Spacing.SM,
            tight=True,
        )
        return _LazySection(
            header=header,
            build_rows=lambda g=group, v=vendor: self._flat_rows(
                g, cap=_SECTION_ROW_CAP, under_vendor=str(v)
            ),
            expanded=any(m.get("model_id") == self._active_id for m in group),
        )

    def _row_icon(
        self, model: dict[str, Any], under_vendor: str | None
    ) -> ft.Control | None:
        """An icon only where it adds information: the LAB behind a
        hosted model when it differs from the section's vendor, and the
        vendor in flat views that have no section context. Under a
        vendor's own first-party rows: nothing - the header said it."""
        vendor = str(model.get("vendor") or "")
        lab = lab_for_model(model)
        lab_icon = model.get("lab_icon_b64")
        if under_vendor is not None:
            # Under a vendor's own section the header already named it;
            # only a DIFFERENT maker adds anything.
            if lab is None or lab.casefold() == under_vendor.casefold():
                return None
            return _avatar(lab, model.get("color"), lab_icon)
        name = lab or vendor
        icon = lab_icon if lab else self._vendor_icons.get(name)
        return _avatar(name, model.get("color"), icon)

    def _model_row(
        self, model: dict[str, Any], *, under_vendor: str | None = None
    ) -> ft.Control:
        model_id = str(model.get("model_id", ""))
        title = display_title(model, under_vendor=under_vendor)
        active = model_id == self._active_id
        # Data-forward right column: the two figures that separate
        # models in practice, muted so the names stay the headline.
        facts = " · ".join(
            part
            for part in (
                format_context_window(model.get("context_window")),
                format_price(model.get("input_price"), model.get("output_price")),
            )
            if part
        )
        trailing: list[ft.Control] = []
        if facts:
            trailing.append(
                SecondaryText(
                    facts,
                    size=Theme.Typography.BODY_SMALL,
                    no_wrap=True,
                    selectable=False,
                )
            )
        if active:
            trailing.append(ft.Icon(ft.Icons.CHECK, size=16, color=Theme.Colors.ACCENT))
        leading = self._row_icon(model, under_vendor)
        return ft.Container(
            content=ft.Row(
                [
                    *([leading] if leading is not None else []),
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
                    *trailing,
                ],
                spacing=Theme.Spacing.SM,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM, vertical=Theme.Spacing.SM
            ),
            border_radius=Theme.Components.BUTTON_RADIUS,
            bgcolor=(
                ft.Colors.with_opacity(0.08, Theme.Colors.ACCENT) if active else None
            ),
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
        # The dialog stays open: the check and tint move to the picked
        # row, and the barrier (or the X) is the way out.
        if self._model_dialog is not None:
            self._model_dialog.set_active(model_id)
        await self._refresh_model_chip()
        self.page.update()

    async def _close_model_picker(self) -> None:
        if self._model_dialog is not None:
            self._model_dialog.open = False
            self.page.update()

    async def _open_model_picker(self) -> None:
        import asyncio

        api = self._api()
        # The catalog and brand icons barely change inside a session;
        # fetch them once and reopen instantly. Only the active model is
        # re-read per open. The first open still makes its three calls
        # CONCURRENTLY - awaiting them one by one tripled the latency.
        cache: tuple[list[dict[str, Any]], dict[str, str]] | None = getattr(
            self, "_model_catalog_cache", None
        )
        if cache is None:
            models, vendors, current = await asyncio.gather(
                api.get("/api/v1/llm/models", {"limit": 200, "usable": True}),
                api.get("/api/v1/llm/vendors", {"usable": True}),
                api.get("/api/v1/llm/current"),
            )
            icons = {
                v["name"]: v["icon_b64"] for v in (vendors or []) if v.get("icon_b64")
            }
            cache = (models or [], icons)
            # An empty catalog is not an answer worth keeping. A stack
            # whose models arrive after the panel was opened (an Ollama
            # sync, a key added) would otherwise show an empty picker for
            # the rest of the session, with a reload as the only cure.
            if models:
                self._model_catalog_cache = cache
        else:
            current = await api.get("/api/v1/llm/current")
        models_cached, vendor_icons = cache
        self._model_dialog = ModelPickerDialog(
            models=models_cached,
            vendor_icons=vendor_icons,
            active_id=str((current or {}).get("model") or ""),
            on_pick=self._pick_model,
            on_close=self._close_model_picker,
        )
        self.page.open(self._model_dialog)
