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

from app.components.frontend.controls import PrimaryText, SecondaryText
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.theme import AegisTheme as Theme

API = "/api/v1/documents"


def has_unread_pages(rows: list[dict[str, Any]]) -> bool:
    """Whether a run would do anything.

    A document with no page rows has never been extracted, so there is
    everything to do; one whose every page is read has nothing, and the
    run would come back "Already extracted".
    """
    return not rows or any(row.get("status") != "read" for row in rows)


def extraction_summary(result: dict[str, Any]) -> str:
    """What the snackbar says when a run lands.

    "Extracted", not "read": reading is what a person does to the page
    afterwards, and the count here is of pages this run took text out of.
    A run that missed some says so against the total, since "5 extracted"
    alone hides the two it could not do.
    """
    extracted = int(result.get("read") or 0)
    missed = int(result.get("unread") or 0)
    if extracted == 0 and missed == 0:
        return "Already extracted"
    if missed == 0:
        return f"{extracted} pages extracted" if extracted != 1 else "1 page extracted"
    return f"{extracted} of {extracted + missed} pages extracted"


class PagesStrip(ft.Row):
    """One tile per extracted page; empty until extraction has run."""

    def __init__(
        self,
        *,
        page: ft.Page,
        api: Callable[[], Any],
        document_id: int,
        on_loaded: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        super().__init__([], wrap=True, spacing=Theme.Spacing.XS)
        self._page = page
        self._api = api
        self._document_id = document_id
        self._on_loaded = on_loaded

    async def load(self) -> None:
        api = self._api()
        fetched = await api.get(f"{API}/{self._document_id}/pages")
        rows: list[dict[str, Any]] = fetched if isinstance(fetched, list) else []
        tiles: list[ft.Control] = []
        for row in rows:
            number = int(row.get("page_number") or 0)
            png = None
            if row.get("has_image"):
                png = await api.get_bytes(
                    f"{API}/{self._document_id}/pages/{number}/image"
                )
            tiles.append(self._tile(number, png, row))
        self.controls = tiles
        if self._on_loaded is not None:
            self._on_loaded(rows)
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
                        PrimaryText(
                            text or detail.get("detail") or "Not extracted yet",
                            selectable=True,
                            size=Theme.Typography.BODY,
                        ),
                        width=380,
                        height=600,
                        bgcolor=Theme.Colors.SURFACE_0,
                        border_radius=6,
                        padding=Theme.Spacing.MD,
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
