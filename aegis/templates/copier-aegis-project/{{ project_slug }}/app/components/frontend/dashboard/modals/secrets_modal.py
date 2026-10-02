"""Secrets component detail modal: every declared credential, and a paste
field for each one this app may set. An unset key reads Missing when
something enabled needs it and Not used when it is only a choice; a key
with a provider check can be tested, and is checked again when saved.

Reads and writes go through the secrets API (``/api/v1/secrets``), which
holds the admin check and the rules (``.env`` wins, read-only stores
refuse). A field is never filled: a value goes in, and only its source and
last four characters come back.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import H3Text, PrimaryText, SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dropdown import NativeDropdown
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.snack_bar import (
    BaseSnackBar,
    ErrorSnackBar,
    SuccessSnackBar,
    WarningSnackBar,
)
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.core.client import error_detail
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from ..cards.secrets_card import counts
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

API = "/api/v1/secrets"
ENV = "env"
SOURCES = {ENV: ".env", "database": "Saved here"}
# A provider check's snack bar, by its result.
VERDICT_BARS: dict[str, type[BaseSnackBar]] = {
    "verified": SuccessSnackBar,
    "unverified": WarningSnackBar,
    "rejected": ErrorSnackBar,
}


def _summary(rows: list[dict[str, Any]]) -> str:
    needed = [r for r in rows if r.get("needed")]
    unused = sum(1 for r in rows if not r.get("needed") and r["source"] is None)
    done = sum(1 for r in needed if r["source"] is not None)
    return f"{done} of {len(needed)} needed keys set · {unused} optional not used"


def _shown(row: dict[str, Any]) -> str:
    if row["source"] is None:
        # Needed by something enabled, or a provider this app could use.
        return "Missing" if row.get("needed") else "Not used"
    source = SOURCES.get(row["source"], str(row["source"]).capitalize())
    hint = row.get("hint")
    if not hint:
        return source
    return f"{source} · {'•••• ' if row.get('secret', True) else ''}{hint}"


class SecretsSection(ft.Column):
    """One row per declared secret, grouped by the code that reads it."""

    def __init__(self, page: ft.Page, writable: bool) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._page = page
        self._writable = writable
        self._fields: dict[str, StyledTextField] = {}

    def did_mount(self) -> None:
        self._page.run_task(self.load)

    async def load(self) -> None:
        api = get_session_state(self._page).api_client
        status, rows = await api.request_with_status("GET", API)
        self.controls.clear()
        self._fields.clear()
        if status != 200 or not isinstance(rows, list):
            self.controls.append(
                SecondaryText(
                    "Secrets are listed and set here by an admin, through the "
                    f"secrets API ({error_detail(rows, status)})."
                )
            )
        else:
            self.controls.append(PrimaryText(_summary(rows)))
            owner = None
            for row in rows:
                if row["owner"] != owner:
                    owner = row["owner"]
                    self.controls.append(H3Text(owner))
                self.controls.append(self._row(row))
        if self.page is not None:
            self.update()

    def _row(self, row: dict[str, Any]) -> ft.Control:
        name = row["name"]
        cells: list[ft.Control] = [
            ft.Column(
                [PrimaryText(name), SecondaryText(_shown(row))],
                spacing=2,
                width=280,
            )
        ]
        if row["source"] and row.get("verifiable"):
            cells.append(
                PulseButton(lambda: self.test(name), "Test", "muted", compact=True)
            )
        if row["source"] == ENV:
            cells.append(SecondaryText("Change it in .env"))
        elif not row.get("live", True):
            # Read through ``settings``: only ``.env`` ever reaches that code.
            cells.append(SecondaryText("Set it in .env"))
        elif self._writable:
            masked = row.get("secret", True)
            field = StyledTextField(
                password=masked,
                can_reveal_password=masked,
                hint_text="Paste a new value" if row["source"] else "Paste the value",
                data=name,
                expand=True,
                compact=True,
            )
            self._fields[name] = field
            if row.get("choosable") and not masked:
                cells.append(
                    PulseButton(lambda: self.pick(name), "Pick", "muted", compact=True)
                )
            cells += [field, PulseButton(lambda: self.save(name), "Save", compact=True)]
            if row["source"]:
                cells.append(
                    PulseButton(
                        lambda: self.remove(name), "Remove", "muted", compact=True
                    )
                )
        return ft.Row(
            cells,
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def pick(self, name: str) -> None:
        """Offer what the provider lists for ``name`` beside its field."""
        api = get_session_state(self._page).api_client
        status, body = await api.request_with_status("GET", f"{API}/{name}/choices")
        if status != 200 or not body:
            WarningSnackBar(f"The provider listed nothing for {name}; type it.").launch(
                self._page
            )
            return
        field = self._fields[name]
        row = next(
            c for c in self.controls if isinstance(c, ft.Row) and field in c.controls
        )
        menu = NativeDropdown(
            options=[ft.dropdown.Option(key=c["value"], text=c["label"]) for c in body],
            on_change=lambda e: self.choose(name, e.control.value),
            hint_text="Pick one",
        )
        row.controls.insert(row.controls.index(field), menu)
        if self.page is not None:
            row.update()

    def choose(self, name: str, value: str) -> None:
        """Fill ``name``'s field with a picked value, still editable."""
        field = self._fields[name]
        field.value = value
        if field.page is not None:
            field.update()

    async def save(self, name: str) -> None:
        value = (self._fields[name].value or "").strip()
        if not value:
            ErrorSnackBar(f"Paste a value for {name}.").launch(self._page)
            return
        api = get_session_state(self._page).api_client
        status, body = await api.request_with_status(
            "PUT", f"{API}/{name}", json={"value": value}
        )
        check = body.get("check") if status == 200 and isinstance(body, dict) else None
        if status != 200:
            await self._done(ErrorSnackBar, error_detail(body, status))
        elif check is None:
            await self._done(SuccessSnackBar, f"{name} saved")
        else:
            word = "verified" if check["result"] == "verified" else "not verified"
            await self._done(
                VERDICT_BARS[check["result"]],
                f"{name} saved, {word}. {check['message']}",
            )

    async def test(self, name: str) -> None:
        """Ask the provider whether the key in effect works."""
        api = get_session_state(self._page).api_client
        status, body = await api.request_with_status("POST", f"{API}/{name}/test")
        if status == 200 and isinstance(body, dict):
            VERDICT_BARS[body["result"]](body["message"]).launch(self._page)
        else:
            ErrorSnackBar(error_detail(body, status)).launch(self._page)

    async def remove(self, name: str) -> None:
        api = get_session_state(self._page).api_client
        status, body = await api.request_with_status("DELETE", f"{API}/{name}")
        if status == 204:
            await self._done(SuccessSnackBar, f"{name} removed")
        else:
            await self._done(ErrorSnackBar, error_detail(body, status))

    async def _done(self, bar: type[BaseSnackBar], message: str) -> None:
        bar(message).launch(self._page)
        await self.load()


class SecretsDetailDialog(BaseDetailPopup):
    """How many credentials are set, and setting the rest."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        writable = bool(metadata.get("writable"))
        overview = ft.Container(
            content=ft.Row(
                [
                    MetricCard(label, value, Theme.Colors.INFO)
                    for label, value in counts(metadata)
                ],
                spacing=Theme.Spacing.MD,
            ),
            padding=Theme.Spacing.MD,
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("secrets"),
            subtitle_text=get_component_subtitle("secrets", metadata),
            sections=[
                overview,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Container(SecretsSection(page, writable), padding=Theme.Spacing.MD),
            ],
            width=900,
            height=620,
            status_detail=get_status_detail(component_data),
        )
