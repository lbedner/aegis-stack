"""The pages of a document, as extraction left them.

A strip of thumbnails from the stored renders (a page number where there
is no image), unread pages dimmed with their reason on hover, and a
click-through to the page at full size with its text beside it.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.theme import AegisTheme as Theme

API = "/api/v1/documents"


def extraction_summary(result: dict[str, Any]) -> str:
    """What the snackbar says when a run lands."""
    read = int(result.get("read") or 0)
    unread = int(result.get("unread") or 0)
    if read == 0 and unread == 0:
        return "Already read"
    if unread == 0:
        return f"{read} pages read" if read != 1 else "1 page read"
    return f"{read} read, {unread} unread"


class PagesStrip(ft.Row):
    """One tile per extracted page; empty until extraction has run."""

    def __init__(
        self, *, page: ft.Page, api: Callable[[], Any], document_id: int
    ) -> None:
        super().__init__([], wrap=True, spacing=Theme.Spacing.XS)
        self._page = page
        self._api = api
        self._document_id = document_id

    async def load(self) -> None:
        api = self._api()
        rows = await api.get(f"{API}/{self._document_id}/pages")
        tiles: list[ft.Control] = []
        for row in rows if isinstance(rows, list) else []:
            number = int(row.get("page_number") or 0)
            png = None
            if row.get("has_image"):
                png = await api.get_bytes(
                    f"{API}/{self._document_id}/pages/{number}/image"
                )
            tiles.append(self._tile(number, png, row))
        self.controls = tiles
        if self.page is not None:
            self.update()

    def _tile(self, number: int, png: bytes | None, row: dict[str, Any]) -> ft.Control:
        unread = row.get("status") != "read"
        face: ft.Control = (
            ft.Image(
                src_base64=base64.b64encode(png).decode(),
                width=48,
                height=64,
                fit=ft.ImageFit.COVER,
            )
            if png
            else SecondaryText(str(number), size=Theme.Typography.BODY_SMALL)
        )
        return ft.Container(
            content=face,
            width=48,
            height=64,
            alignment=ft.alignment.center,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=4,
            opacity=0.45 if unread else 1.0,
            tooltip=(row.get("detail") or f"Page {number}")
            if unread
            else f"Page {number}",
            ink=True,
            on_click=lambda _e, n=number, p=png: self._page.run_task(self._open, n, p),
        )

    async def _open(self, number: int, png: bytes | None) -> None:
        """A page at full size with its text beside it."""
        fetched = await self._api().get(f"{API}/{self._document_id}/pages/{number}")
        detail: dict[str, Any] = fetched if isinstance(fetched, dict) else {}
        text = detail.get("text")
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
                self._page.update()

        image: ft.Control = (
            ft.Image(src_base64=base64.b64encode(png).decode(), fit=ft.ImageFit.CONTAIN)
            if png
            else SecondaryText("No image for this page")
        )
        dialog = StyledAlertDialog(
            title=f"Page {number}",
            body=ft.Row(
                [
                    ft.Container(image, width=460, height=600),
                    ft.Container(
                        SecondaryText(
                            text or detail.get("detail") or "Not read yet",
                            selectable=True,
                        ),
                        width=380,
                        height=600,
                    ),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.START,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=900,
            on_close=_close,
        )
        self._page.open(dialog)
