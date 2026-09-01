"""The chat panel's image-attach flow: pick, upload, chip, send.

One mixin of ``ChatPanel``. Browser-side picks upload through the same
signed ``/dashboard/upload`` endpoint the register's file imports use;
the bytes are read server-side, base64-encoded, and held as pending
attachments until the next send, where they ride the chat request body
(see ``services/ai/domains/chat/attachments.py`` for the wire shape).
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
from typing import Any

import flet as ft

from app.components.frontend.controls.busy_bar import busy_bar
from app.components.frontend.controls.chat.stream import image_media_type
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.controls.uploads import BrowserUploads
from app.components.frontend.theme import AegisTheme as Theme
from app.core.log import logger


class ReplayRetention:
    """Keeps recent turns' sent images re-sendable from session memory.

    Each user bubble's replay closure holds the very list retained here,
    so replay can re-send the original screenshots without re-pasting.
    Bounded because screenshots are megabytes: past ``max_turns``
    image-carrying turns, the oldest list is cleared IN PLACE - the
    closure sees it empty and that replay quietly becomes text-only,
    exactly like a history-reloaded bubble (bytes are never persisted).
    """

    def __init__(self, max_turns: int = 8) -> None:
        self._turns: deque[list[dict[str, str]]] = deque()
        self._max_turns = max_turns

    def retain(self, attachments: list[dict[str, str]]) -> None:
        if not attachments:
            return
        self._turns.append(attachments)
        while len(self._turns) > self._max_turns:
            self._turns.popleft().clear()


class AttachmentsMixin:
    """Pick images, stage them as chips, send them with the message."""

    # Provided by ChatPanel
    page: ft.Page
    _pending_attachments: list[dict[str, str]]
    _uploads: BrowserUploads
    _attach_chips: ft.Row
    _attachment_bar: ft.Container
    _attach_button: Any
    _retained: ReplayRetention

    def _api(self) -> Any: ...  # real definition on ChatPanel

    def _build_attachment_controls(self) -> None:
        """Constructor half: the picker, the chips row, the bar, the button."""
        from app.components.frontend.controls.buttons import BaseIconButton

        self._pending_attachments = []
        self._retained = ReplayRetention()
        self._uploads = BrowserUploads(
            on_file=self._ingest_attachment, on_change=self._sync_receiving
        )
        self._attach_chips = ft.Row([], wrap=True, spacing=Theme.Spacing.XS)
        self._receiving = ft.Row(
            [
                busy_bar(width=120),
                SecondaryText("Receiving image...", size=Theme.Typography.CAPTION),
            ],
            spacing=Theme.Spacing.SM,
            visible=False,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._attachment_bar = ft.Container(
            content=ft.Column(
                [self._attach_chips, self._receiving], spacing=Theme.Spacing.XS
            ),
            visible=False,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.SM),
        )
        self._attach_button = BaseIconButton(
            self._open_attach_picker,
            ft.Icons.ATTACH_FILE_OUTLINED,
            tooltip="Attach images",
        )

    def _mount_attachments(self) -> None:
        """did_mount half: overlay the picker (it must live in
        page.overlay to render, and revisits must not append it twice)
        and start the pastebox watch."""
        if self._uploads.picker not in self.page.overlay:
            self._uploads.mount(self.page)
            self.page.update()
        self.page.run_task(self._watch_pastebox)

    async def _watch_pastebox(self) -> None:
        """Poll-drain the pastebox while mounted.

        An OS-clipboard paste anywhere on the dashboard is captured
        browser-side and staged at ``/api/v1/pastebox`` (the page's
        injected script); this loop pulls it into the pending chips so
        a paste behaves exactly like a picked file. Drain-once: with
        two chat surfaces open, the first poll wins the paste."""
        receiving = False
        while self.page is not None:
            try:
                data = await self._api().post("/api/v1/pastebox/drain")
                items = data.get("items") if isinstance(data, dict) else None
                incoming = data.get("incoming", 0) if isinstance(data, dict) else 0
                if items:
                    self._pending_attachments.extend(items)
                receiving = bool(incoming) or self._uploads.in_flight
                if items or receiving != self._receiving.visible:
                    self._receiving.visible = receiving
                    self._refresh_attachment_chips()
            except Exception as exc:  # noqa: BLE001 - a dead poll must not kill the panel
                logger.warning("chat_attachment.pastebox_poll_failed", error=str(exc))
            # Tighten the cadence while something is in transit so the
            # indicator and the arriving chip both feel immediate.
            await asyncio.sleep(0.75 if receiving else 2.5)

    async def _open_attach_picker(self) -> None:
        self._uploads.pick(
            dialog_title="Attach images",
            allow_multiple=True,
            allowed_extensions=["png", "jpg", "jpeg", "webp", "gif"],
        )

    def _sync_receiving(self) -> None:
        """The indicator follows what is still in transit."""
        self._receiving.visible = self._uploads.in_flight
        self._refresh_attachment_chips()

    async def _ingest_attachment(self, name: str, data: bytes) -> None:
        """An upload arrived: stage it as a pending attachment."""
        media_type = image_media_type(name)
        if media_type is None:
            ErrorSnackBar(f"{name} is not an image.").launch(self.page)
            return
        self._pending_attachments.append(
            {
                "media_type": media_type,
                "data_b64": base64.b64encode(data).decode(),
                "name": name,
            }
        )
        self._refresh_attachment_chips()

    def _remove_attachment(self, attachment: dict[str, str]) -> None:
        if attachment in self._pending_attachments:
            self._pending_attachments.remove(attachment)
        self._refresh_attachment_chips()

    def _take_attachments(self) -> list[dict[str, str]]:
        """The send handoff: everything staged, cleared in one move."""
        taken, self._pending_attachments = self._pending_attachments, []
        self._refresh_attachment_chips()
        return taken

    def _refresh_attachment_chips(self) -> None:
        self._attach_chips.controls = [
            self._attachment_chip(a) for a in self._pending_attachments
        ]
        self._attach_chips.visible = bool(self._pending_attachments)
        self._attachment_bar.visible = (
            bool(self._pending_attachments) or self._receiving.visible
        )
        if self._attachment_bar.page is not None:
            self._attachment_bar.update()

    def _attachment_chip(self, attachment: dict[str, str]) -> ft.Control:
        # The chip leads with the image itself: a thumbnail from the
        # staged bytes (already in session memory), clickable for full
        # size - a filename alone cannot tell two screenshots apart.
        thumbnail = ft.Container(
            content=ft.Image(
                src_base64=attachment["data_b64"],
                width=28,
                height=28,
                fit=ft.ImageFit.COVER,
                border_radius=Theme.Components.BUTTON_RADIUS,
            ),
            on_click=lambda _e, a=attachment: self._open_attachment_preview(a),
            tooltip="View full size",
        )
        return ft.Container(
            content=ft.Row(
                [
                    thumbnail,
                    SecondaryText(
                        attachment.get("name") or "image",
                        size=Theme.Typography.CAPTION,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=12,
                        icon_color=Theme.Colors.TEXT_SECONDARY,
                        tooltip="Remove",
                        style=ft.ButtonStyle(padding=0),
                        width=20,
                        height=20,
                        on_click=lambda _e, a=attachment: self._remove_attachment(a),
                    ),
                ],
                spacing=Theme.Spacing.XS,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.SM, vertical=2),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.BUTTON_RADIUS,
        )

    def _open_attachment_preview(self, attachment: dict[str, str]) -> None:
        """The chip's click-through: the staged image at full size."""
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
                self.page.update()

        dialog = StyledAlertDialog(
            title=attachment.get("name") or "image",
            body=ft.Container(
                content=ft.Image(
                    src_base64=attachment["data_b64"], fit=ft.ImageFit.CONTAIN
                ),
                height=480,
                alignment=ft.alignment.center,
            ),
            width=640,
            on_close=_close,
        )
        self.page.open(dialog)

    @staticmethod
    def attachment_note(attachments: list[dict[str, str]]) -> str:
        """The transcript line under a user bubble that carried images."""
        if not attachments:
            return ""
        names = ", ".join(a.get("name") or "image" for a in attachments)
        return f"Attached: {names}"

    def _attachment_note_row(
        self, attachments: list[dict[str, str]]
    ) -> ft.Control | None:
        """The right-aligned transcript row under a user bubble that
        carried images, or None when it carried none."""
        if not attachments:
            return None
        return ft.Row(
            [
                SecondaryText(
                    self.attachment_note(attachments),
                    size=Theme.Typography.CAPTION,
                )
            ],
            alignment=ft.MainAxisAlignment.END,
        )


def attachment_payload(attachments: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The request-body shape for staged attachments (already wire-ready;
    exists so the panel and any future surface share one contract)."""
    return [
        {
            "media_type": a["media_type"],
            "data_b64": a["data_b64"],
            "name": a.get("name"),
        }
        for a in attachments
    ]
