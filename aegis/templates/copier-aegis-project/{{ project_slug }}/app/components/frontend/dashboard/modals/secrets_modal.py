"""Secrets component detail modal: every declared credential, and a paste
field for each one this app may set; below them the settings marked
``Configurable``, whose saved values apply when the app restarts. An unset key reads Missing when
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
from app.core import saved_settings, secrets
from app.core.client import error_detail
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from ..cards.secrets_card import counts
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

API = "/api/v1/secrets"
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


def _status(row: dict[str, Any]) -> secrets.SecretStatus:
    """The API's row as core's status (it is ``asdict`` of one), so the
    wording of its state and value is core's."""
    return secrets.SecretStatus(**row)


def _shown(row: dict[str, Any]) -> str:
    status = _status(row)
    value = status.in_effect
    if not value or not (status.is_set or status.setting):
        return status.state
    return f"{status.state} · {'•••• ' if status.secret else ''}{value}"


def _menu(offered: list[dict[str, str]], **kwargs: Any) -> NativeDropdown:
    """A dropdown of the API's choices for a name."""
    options = [ft.dropdown.Option(key=c["value"], text=c["label"]) for c in offered]
    return NativeDropdown(options=options, hint_text="Pick one", **kwargs)


class SecretsSection(ft.Column):
    """One row per declared secret (or, with ``setting``, per saved
    setting), grouped by the code that reads it."""

    def __init__(self, page: ft.Page, writable: bool, setting: bool = False) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._page = page
        self._writable = writable
        self._setting = setting
        self._list = f"{API}?setting=true" if setting else API
        self._fields: dict[str, ft.TextField | ft.Dropdown] = {}
        # A setting's closed set of values, by name: picked, never typed.
        self._offered: dict[str, list[dict[str, str]]] = {}

    @property
    def _api(self) -> Any:
        return get_session_state(self._page).api_client

    def did_mount(self) -> None:
        self._page.run_task(self.load)

    async def load(self) -> None:
        status, rows = await self._api.request_with_status("GET", self._list)
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
            if self._setting:
                self._offered = {
                    row["name"]: offered
                    for row in rows
                    if row.get("choosable")
                    and (offered := await self._choices(row["name"]))
                }
            self.controls.append(
                SecondaryText("Saved values apply when the app restarts.")
                if self._setting
                else PrimaryText(_summary(rows))
            )
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
        if row["source"] == secrets.ENV:
            cells.append(SecondaryText("Change it in .env"))
        elif not row.get("live", True):
            # Read through ``settings``: only ``.env`` ever reaches that code.
            cells.append(SecondaryText("Set it in .env"))
        elif self._writable:
            masked = row.get("secret", True)
            field = self._field(row)
            self._fields[name] = field
            if row.get("choosable") and not masked and name not in self._offered:
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

    def _field(self, row: dict[str, Any]) -> ft.TextField | ft.Dropdown:
        """A setting with a closed set of values is a dropdown at the value
        in effect; anything else is typed, a key masked."""
        offered = self._offered.get(row["name"])
        if offered:
            return _menu(offered, value=_status(row).in_effect)
        masked = row.get("secret", True)
        return StyledTextField(
            password=masked,
            can_reveal_password=masked,
            hint_text="Paste a new value" if row["source"] else "Paste the value",
            data=row["name"],
            expand=True,
            compact=True,
        )

    async def _choices(self, name: str) -> list[dict[str, str]]:
        """What ``name`` may be set to (the API's choices); empty if nothing."""
        status, body = await self._api.request_with_status(
            "GET", f"{API}/{name}/choices"
        )
        return body if status == 200 and isinstance(body, list) else []

    async def pick(self, name: str) -> None:
        """Offer what the provider lists for ``name`` beside its field."""
        body = await self._choices(name)
        if not body:
            WarningSnackBar(f"The provider listed nothing for {name}; type it.").launch(
                self._page
            )
            return
        field = self._fields[name]
        row = next(
            c for c in self.controls if isinstance(c, ft.Row) and field in c.controls
        )
        menu = _menu(body, on_change=lambda e: self.choose(name, e.control.value))
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
        status, body = await self._api.request_with_status(
            "PUT", f"{API}/{name}", json={"value": value}
        )
        check = body.get("check") if status == 200 and isinstance(body, dict) else None
        if status != 200:
            await self._done(ErrorSnackBar, error_detail(body, status))
        elif check is None:
            await self._done(SuccessSnackBar, saved_settings.saved(name))
        else:
            await self._done(
                VERDICT_BARS[check["result"]],
                saved_settings.saved(name, check["result"], check["message"]),
            )

    async def test(self, name: str) -> None:
        """Ask the provider whether the key in effect works."""
        status, body = await self._api.request_with_status("POST", f"{API}/{name}/test")
        if status == 200 and isinstance(body, dict):
            VERDICT_BARS[body["result"]](body["message"]).launch(self._page)
        else:
            ErrorSnackBar(error_detail(body, status)).launch(self._page)

    async def remove(self, name: str) -> None:
        status, body = await self._api.request_with_status("DELETE", f"{API}/{name}")
        if status == 204:
            await self._done(SuccessSnackBar, saved_settings.removed(name))
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
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Container(
                    ft.Column(
                        [
                            H3Text("Settings"),
                            SecretsSection(page, writable, setting=True),
                        ]
                    ),
                    padding=Theme.Spacing.MD,
                ),
            ],
            width=900,
            height=620,
            status_detail=get_status_detail(component_data),
        )
