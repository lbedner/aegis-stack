"""The selected document: what it is, what it is called, what it is for.

Right-hand pane of the Documents tab. Edits go through PATCH, tags
through their own routes, and the bytes never move: Download opens the
content route, Delete retires the row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    FormDropdown,
    FormTextField,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.form_fields import FormDateField
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_bytes, format_date
from app.core.log import logger
from app.services.documents.models import DOCUMENT_KINDS

from .modal_sections import EmptyStatePlaceholder

API = "/api/v1/documents"
KIND_OPTIONS = [(kind, kind.title()) for kind in DOCUMENT_KINDS]


def _facts(doc: dict[str, Any]) -> str:
    parts = [format_bytes(int(doc.get("byte_size") or 0))]
    if doc.get("page_count"):
        parts.append(f"{doc['page_count']} pages")
    parts.append(str(doc.get("media_type") or "unknown type"))
    if doc.get("received_at"):
        parts.append(f"received {format_date(doc['received_at'])}")
    return " . ".join(parts)


class DocumentDetailPane(ft.Container):
    """Shows one document and lets the user correct its metadata."""

    def __init__(self, page: ft.Page, on_change: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self.page = page
        self._on_change = on_change
        self._doc: dict[str, Any] | None = None
        self.width = 380
        self.content = EmptyStatePlaceholder("Select a document")

    def _api(self) -> Any:
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self.page).api_client

    def clear(self) -> None:
        self._doc = None
        self.content = EmptyStatePlaceholder("Select a document")
        if self.page:
            self.update()

    def show(self, doc: dict[str, Any]) -> None:
        self._doc = doc
        self._title = FormTextField(label="Title", value=str(doc.get("title") or ""))
        self._kind = FormDropdown(
            label="Kind", value=str(doc.get("kind") or "other"), options=KIND_OPTIONS
        )
        self._date = FormDateField(
            label="Document date", value=str(doc.get("document_date") or "")
        )
        self._note = FormTextField(
            label="Note",
            value=str(doc.get("note") or ""),
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        self._tag_input = FormTextField(
            label="Add tag", hint="Enter to add", on_submit=self._add_tag
        )
        self.content = ft.Column(
            [
                H3Text(str(doc.get("title") or "Untitled")),
                SecondaryText(_facts(doc), size=Theme.Typography.BODY_SMALL),
                self._title,
                self._kind,
                self._date,
                self._note,
                ft.Row(self._tag_chips(), wrap=True, spacing=Theme.Spacing.XS),
                ft.Row(
                    [
                        ft.Container(self._tag_input, expand=True),
                        PulseButton(
                            on_click_callable=self._add_tag,
                            text="Add",
                            variant="muted",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                SecondaryText(
                    str(doc.get("storage_key") or ""),
                    size=Theme.Typography.CAPTION,
                    selectable=True,
                ),
                ft.Row(
                    [
                        PulseButton(
                            on_click_callable=self._save, text="Save", compact=True
                        ),
                        PulseButton(
                            on_click_callable=self._download,
                            text="Download",
                            variant="muted",
                            compact=True,
                        ),
                        PulseButton(
                            on_click_callable=self._confirm_delete,
                            text="Delete",
                            variant="stop",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        if self.page:
            self.update()

    def _tag_chips(self) -> list[ft.Control]:
        tags = self._doc.get("tags", []) if self._doc else []
        return [
            ft.Chip(
                label=SecondaryText(str(tag), size=Theme.Typography.BODY_SMALL),
                on_delete=lambda _e, t=str(tag): self.page.run_task(self._untag, t),
            )
            for tag in tags
        ]

    async def _refreshed(self, body: Any) -> None:
        """A route answered with the document: show it and tell the list."""
        if isinstance(body, dict):
            self.show(body)
        await self._on_change()

    async def _save(self) -> None:
        if self._doc is None:
            return
        payload = {
            "title": self._title.value,
            "kind": self._kind.value,
            "document_date": self._date.value or None,
            "note": self._note.value or None,
        }
        code, body = await self._api().request_with_status(
            "PATCH", f"{API}/{self._doc['id']}", json=payload
        )
        if code != 200:
            detail = body.get("detail") if isinstance(body, dict) else None
            ErrorSnackBar(str(detail or "Save failed.")).launch(self.page)
            return
        SuccessSnackBar("Saved.").launch(self.page)
        await self._refreshed(body)

    async def _add_tag(self, _e: ft.ControlEvent | None = None) -> None:
        """Enter in the field or the Add button; both land here."""
        label = (self._tag_input.value or "").strip()
        logger.info(
            "documents.tag_add",
            document_id=self._doc["id"] if self._doc else None,
            label=label,
        )
        if self._doc is None or not label:
            return
        self._tag_input.value = ""
        body = await self._api().post(
            f"{API}/{self._doc['id']}/tags", json={"label": label}
        )
        await self._refreshed(body)

    async def _untag(self, label: str) -> None:
        if self._doc is None:
            return
        body = await self._api().delete(
            f"{API}/{self._doc['id']}/tags/{quote(label, safe='')}"
        )
        await self._refreshed(body)

    async def _download(self) -> None:
        if self._doc is not None:
            self.page.launch_url(f"{API}/{self._doc['id']}/content")

    async def _confirm_delete(self) -> None:
        if self._doc is None:
            return
        title = str(self._doc.get("title") or "this document")

        async def _do_delete() -> None:
            if self._doc is None:
                return
            await self._api().delete(f"{API}/{self._doc['id']}")
            self.clear()
            await self._on_change()

        ConfirmDialog(
            page=self.page,
            title="Delete document?",
            message=(
                f'"{title}" will be retired from the list. The stored file is kept.'
            ),
            confirm_text="Delete",
            destructive=True,
            on_confirm=_do_delete,
        ).show()
