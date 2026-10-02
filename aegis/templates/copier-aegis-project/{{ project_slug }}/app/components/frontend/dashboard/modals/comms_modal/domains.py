"""The Email tab's sending domains: Resend sends only from a verified one.

Read and changed through the comms API (``/api/v1/comms/domains``): each
domain with its status and a Check, and Add, which shows the DNS records
to create at the registrar.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import H3Text, PrimaryText, SecondaryText, Tag
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
    WarningSnackBar,
)
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.core.client import error_detail

API = "/api/v1/comms/domains"


class DomainsSection(ft.Column):
    """The account's domains, a Check each, and Add with its DNS records."""

    def __init__(self, page: ft.Page | None = None) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._page_ref = page
        self._new = StyledTextField(
            hint_text="mail.example.com", compact=True, expand=True
        )
        self._records = ft.Column(spacing=2)

    @property
    def _host(self) -> ft.Page:
        return self._page_ref or self.page

    def did_mount(self) -> None:
        self._host.run_task(self.load)

    async def load(self) -> None:
        api = get_session_state(self._host).api_client
        status, body = await api.request_with_status("GET", API)
        self.controls = [H3Text("Sending domains")]
        if status != 200 or not isinstance(body, list):
            self.controls.append(SecondaryText(error_detail(body, status)))
        else:
            self.controls += [self._row(d) for d in body] or [
                SecondaryText("No domains yet")
            ]
            self.controls.append(
                ft.Row(
                    [self._new, PulseButton(self.add, "Add domain", compact=True)],
                    spacing=Theme.Spacing.SM,
                )
            )
            self.controls.append(self._records)
        if self.page is not None:
            self.update()

    def _row(self, domain: dict[str, Any]) -> ft.Control:
        name = domain["name"]
        tone = Theme.Colors.SUCCESS if domain["verified"] else Theme.Colors.WARNING
        return ft.Row(
            [
                PrimaryText(name, width=260),
                Tag(text=str(domain["status"]).capitalize(), color=tone),
                PulseButton(lambda: self.check(name), "Check", "muted", compact=True),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def check(self, name: str) -> None:
        """Ask Resend to check the domain's DNS now."""
        api = get_session_state(self._host).api_client
        status, body = await api.request_with_status("POST", f"{API}/{name}/check")
        if status != 200 or not isinstance(body, dict):
            ErrorSnackBar(error_detail(body, status)).launch(self._host)
            return
        bar = SuccessSnackBar if body["verified"] else WarningSnackBar
        bar(f"{name}: {body['status']}").launch(self._host)
        await self.load()

    async def add(self) -> None:
        """Add the domain and show the records to create."""
        name = (self._new.value or "").strip()
        if not name:
            ErrorSnackBar("Type a domain first.").launch(self._host)
            return
        api = get_session_state(self._host).api_client
        status, body = await api.request_with_status("POST", API, json={"domain": name})
        if status != 200 or not isinstance(body, dict):
            ErrorSnackBar(error_detail(body, status)).launch(self._host)
            return
        await self.load()
        self._records.controls = [
            SecondaryText(f"Create these records for {body['domain']}, then Check:"),
            *[
                ft.Text(
                    f"{r['type']}  {r['host']}  {r['value']}", selectable=True, size=12
                )
                for r in body["records"]
            ],
        ]
        if self.page is not None:
            self.update()
