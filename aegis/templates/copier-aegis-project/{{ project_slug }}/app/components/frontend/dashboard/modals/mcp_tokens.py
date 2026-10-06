"""The MCP modal's tokens (with auth): the viewer's own, made, listed and
revoked through the token API (``/api/v1/mcp/tokens``), which says whose
they are. A new token's value is shown here once, until the list reloads;
the same table and wording as htmx's Tokens section (``ui_mcp``)."""

from typing import Any

import flet as ft

from app.components.frontend.controls import ConfirmDialog, H3Text, SecondaryText
from app.components.frontend.controls.buttons import IconCopyButton, PulseButton
from app.components.frontend.controls.dropdown import NativeDropdown
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme
from app.core.client import error_detail
from app.services.system import ui_mcp

from .table_tab import TableTab, columns_of

API = "/api/v1/mcp/tokens"


class McpTokensSection(ft.Column):
    """A form to make a token, the one just made (value and all), and the
    viewer's live tokens, each revocable."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._page = page
        self._name = StyledTextField(hint_text="What it is for: laptop, CI", width=280)
        self._scope = NativeDropdown(
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in ui_mcp.SCOPE_LABELS.items()
            ],
            value="read",
            enable_filter=False,
            enable_search=False,
            width=200,
        )
        self._made: ft.Control | None = None
        self._listed: ft.Control = SecondaryText("Reading your tokens.")

    @property
    def _api(self) -> Any:
        return get_session_state(self._page).api_client

    def did_mount(self) -> None:
        self._page.run_task(self.load)

    async def load(self) -> None:
        """The list again; a value shown once is gone from it."""
        self._made = None
        status, rows = await self._api.request_with_status("GET", API)
        self._listed = (
            TableTab(
                [ui_mcp.token_row(row) for row in rows],
                columns_of(ui_mcp.TOKEN_COLUMNS),
                ui_mcp.NO_TOKENS,
                actions=self._revoke_button,
            )
            if status == 200 and isinstance(rows, list)
            else SecondaryText(error_detail(rows, status))
        )
        self._render()

    def _render(self) -> None:
        form = ft.Row(
            [
                self._name,
                self._scope,
                PulseButton(self._on_make, "Make token", compact=True),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.controls = [H3Text("Your tokens"), form]
        if self._made is not None:
            self.controls.append(self._made)
        self.controls.append(self._listed)
        if self.page is not None:
            self.update()

    async def _on_make(self) -> None:
        await self.make((self._name.value or "").strip(), self._scope.value or "read")

    async def make(self, name: str, scope: str) -> None:
        """Make a token and show its value, this once."""
        if not name:
            ErrorSnackBar("Name the token.").launch(self._page)
            return
        status, body = await self._api.request_with_status(
            "POST", API, json={"name": name, "scope": scope}
        )
        if status != 201 or not isinstance(body, dict):
            ErrorSnackBar(error_detail(body, status)).launch(self._page)
            return
        value = body["token"]
        self._name.value = ""
        self._made = ft.Column(
            [
                ft.Row(
                    [SecondaryText(value, selectable=True), IconCopyButton(lambda: value)],
                    spacing=Theme.Spacing.XS,
                ),
                SecondaryText(ui_mcp.SHOWN_ONCE),
            ],
            spacing=2,
        )
        self._render()

    def _revoke_button(self, row: dict[str, Any]) -> ft.Control:
        async def confirmed() -> None:
            await self.revoke(row["id"])

        def ask() -> None:
            ConfirmDialog(
                page=self._page,
                title="Revoke token",
                message=f"Revoke {row['name']}? A client using it is refused on its next request.",
                confirm_text="Revoke",
                on_confirm=confirmed,
                destructive=True,
            ).show()

        return PulseButton(ask, "Revoke", "muted", compact=True)

    async def revoke(self, token_id: int) -> None:
        """Revoke a token: it fails on its next use."""
        status, body = await self._api.request_with_status("DELETE", f"{API}/{token_id}")
        if status != 204:
            ErrorSnackBar(error_detail(body, status)).launch(self._page)
            return
        SuccessSnackBar("Token revoked").launch(self._page)
        await self.load()
