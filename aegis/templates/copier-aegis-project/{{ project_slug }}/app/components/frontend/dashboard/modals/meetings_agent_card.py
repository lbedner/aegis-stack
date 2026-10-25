"""An agent's card in a call, in its row of the Flet Overseer's Agents tab:
its picture (else its initials), a button to change it, and whether its
camera is on. The same as the htmx Overseer's, over the admin API
(``api/meetings/admin.py``)."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
import mimetypes
from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText, ThemedSwitch
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.uploads import BrowserUploads
from app.components.frontend.theme import AegisTheme as Theme
from app.services.meetings.service import IMAGE_TYPES

from .meetings_follow import api

AGENTS = "/api/v1/meetings/admin/agents"
# What the picker offers: what the card takes.
EXTENSIONS = sorted(
    {ext.lstrip(".") for t in IMAGE_TYPES for ext in mimetypes.guess_all_extensions(t)}
)
SIZE = 32


def face(row: dict[str, Any], picture: bytes | None) -> ft.Control:
    """The agent's picture, else its initials, in a circle."""
    if picture is None:
        return ft.CircleAvatar(content=SecondaryText(row["initials"]), radius=SIZE // 2)
    # Raster pictures decode whatever the address names; an SVG (markup)
    # renders only named as one.
    kind = "image/svg+xml" if picture.lstrip()[:1] == b"<" else "image/png"
    # A data: address, not src_base64: that is decoded again on every
    # remount, and the tile flashes empty.
    encoded = base64.b64encode(picture).decode()
    return ft.Image(
        src=f"data:{kind};base64,{encoded}",
        width=SIZE,
        height=SIZE,
        fit=ft.ImageFit.COVER,
        border_radius=SIZE // 2,
    )


class AgentCard(ft.Row):
    """One agent's card (``row``, the admin API's ``AgentRow``) with its
    picture's bytes when it has one; ``changed`` reloads the tab."""

    def __init__(
        self,
        page: ft.Page,
        row: dict[str, Any],
        picture: bytes | None,
        changed: Callable[[], Awaitable[None]],
    ) -> None:
        self._page = page
        self._name = str(row["account"]["name"])
        self._changed = changed
        self._uploads = BrowserUploads(self._upload)
        self.camera = ThemedSwitch(
            value=bool(row["account"]["camera"]),
            on_change=lambda e: page.run_task(self._camera, bool(e.control.value)),
        )
        pick = PulseButton(
            on_click_callable=self._pick,
            text="Change picture" if picture else "Add picture",
            variant="muted",
            compact=True,
        )
        super().__init__(
            [face(row, picture), pick, SecondaryText("Camera"), self.camera],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def _pick(self) -> None:
        self._uploads.mount(self._page)
        self._page.update()
        self._uploads.pick(
            dialog_title="The agent's picture",
            allow_multiple=False,
            allowed_extensions=EXTENSIONS,
        )

    async def _send(self, method: str, path: str, **sent: Any) -> bool:
        """``method`` on the agent's ``path``; what the API refused is said."""
        code, body = await api(self._page).request_with_status(
            method, f"{AGENTS}/{self._name}/{path}", **sent
        )
        if code < 300:
            return True
        detail = body.get("detail") if isinstance(body, dict) else None
        ErrorSnackBar(str(detail or f"{self._name}'s card was not changed.")).launch(
            self._page
        )
        return False

    async def _upload(self, filename: str, data: bytes) -> None:
        kind = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if await self._send("POST", "image", files={"file": (filename, data, kind)}):
            await self._changed()

    async def _camera(self, on: bool) -> None:
        if not await self._send("PUT", "camera", json={"on": on}):
            self.camera.value = not on
            if self.camera.page:
                self.camera.update()
