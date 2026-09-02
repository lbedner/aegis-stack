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
    LabelText,
    PrimaryText,
    SecondaryText,
    ThemedSwitch,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import FormDateField
from app.components.frontend.controls.loading_overlay import LoadingOverlay
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_bytes, format_date
from app.core.log import logger
from app.services.documents.models import DOCUMENT_KINDS

from .documents_pages import PagesStrip, extraction_summary
from .modal_sections import EmptyStatePlaceholder

API = "/api/v1/documents"
KIND_OPTIONS = [(kind, kind.title()) for kind in DOCUMENT_KINDS]
# How paper tends to arrive. Free text on the row; these are the offers.
CHANNELS = ("mail", "download", "scan", "email", "upload")
# Flet's dropdown reports an option with an EMPTY key by its text, so
# "no value" needs a real key or "Nothing" arrives as a value.
NONE = "none"


def _chosen(value: str | None) -> str | None:
    """A dropdown value, with the placeholder read as no value."""
    return None if value in (None, "", NONE) else value


def _pair(left: ft.Control, right: ft.Control) -> ft.Row:
    """Two fields on one line, equal width."""
    return ft.Row(
        [ft.Container(left, expand=True), ft.Container(right, expand=True)],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def replaces_options(
    docs: list[dict[str, Any]], *, current_id: int | None
) -> list[tuple[str, str]]:
    """Dropdown options for "this replaces": nothing, or any other document."""
    return [(NONE, "Nothing")] + [
        (str(doc["id"]), str(doc.get("title") or "Untitled"))
        for doc in docs
        if doc.get("id") != current_id
    ]


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
        self._others: list[dict[str, Any]] = []
        self.width = 400
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.border = ft.border.all(1, ft.Colors.OUTLINE_VARIANT)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.content = EmptyStatePlaceholder("Select a document")

    def _api(self) -> Any:
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self.page).api_client

    def clear(self) -> None:
        self._doc = None
        self.content = EmptyStatePlaceholder("Select a document")
        if self.page:
            self.update()

    def show(
        self, doc: dict[str, Any], others: list[dict[str, Any]] | None = None
    ) -> None:
        self._doc = doc
        if others is not None:
            self._others = others
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
        self._channel = FormDropdown(
            label="Received via",
            value=str(doc.get("channel") or NONE),
            options=[(NONE, "Unknown"), *[(c, c.title()) for c in CHANNELS]],
        )
        self._replaces = FormDropdown(
            label="Replaces",
            value=str(doc.get("supersedes_id") or NONE),
            options=replaces_options(self._others, current_id=doc.get("id")),
        )
        self._protected = ThemedSwitch(value=bool(doc.get("protected")))
        self._pages = PagesStrip(
            page=self.page, api=self._api, document_id=int(doc["id"])
        )
        self._tag_input = FormTextField(
            label="Add tag", hint="Enter to add", on_submit=self._add_tag
        )
        hairline = ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT)
        header = ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(
                            H3Text(str(doc.get("title") or "Untitled")), expand=True
                        ),
                        ft.Icon(
                            ft.Icons.LOCK_OUTLINE,
                            size=16,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            visible=bool(doc.get("protected")),
                            tooltip="Protected",
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                SecondaryText(
                    _facts(doc),
                    size=Theme.Typography.BODY_SMALL,
                    tooltip=str(doc.get("storage_key") or ""),
                ),
                self._pages,
            ],
            spacing=Theme.Spacing.XS,
            tight=True,
        )
        body = ft.Column(
            [
                self._title,
                _pair(self._kind, self._date),
                _pair(self._channel, self._replaces),
                ft.Column(
                    [
                        ft.Row(
                            [PrimaryText("Protected"), self._protected],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        SecondaryText(
                            "Delete asks for the title. Never auto-purged.",
                            size=Theme.Typography.CAPTION,
                        ),
                    ],
                    spacing=0,
                    tight=True,
                ),
                self._note,
                LabelText("Tags"),
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
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        footer = ft.Row(
            [
                PulseButton(on_click_callable=self._save, text="Save", compact=True),
                ft.Container(expand=True),
                PulseButton(
                    on_click_callable=self._extract,
                    text="Extract",
                    variant="muted",
                    compact=True,
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
        )
        self.content = ft.Column(
            [header, hairline, body, hairline, footer],
            spacing=Theme.Spacing.SM,
            expand=True,
        )
        if self.page:
            self.update()
            self.page.run_task(self._pages.load)

    async def _extract(self) -> None:
        """Read every page not yet read; progress rides the jobs stream."""
        if self._doc is None:
            return
        overlay = LoadingOverlay(self.page)
        overlay.show("Opening the document...")
        started = await self._api().post(
            f"{API}/{self._doc['id']}/extract?background=true"
        )
        if not isinstance(started, dict) or not started.get("job_id"):
            overlay.fail("Extraction could not start.", title="Extraction failed")
            return
        result = await overlay.run_job(
            self._api(), str(started["job_id"]), title="Extraction failed"
        )
        if result is None:
            return
        SuccessSnackBar(extraction_summary(result)).launch(self.page)
        await self._pages.load()
        await self._on_change()

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
        replaces = _chosen(self._replaces.value)
        payload = {
            "title": self._title.value,
            "kind": self._kind.value,
            "document_date": self._date.value or None,
            "note": self._note.value or None,
            "channel": _chosen(self._channel.value),
            "supersedes_id": int(replaces) if replaces else None,
            "protected": bool(self._protected.value),
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
        if self._doc.get("protected"):
            self._confirm_protected_delete(title)
            return

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

    def _confirm_protected_delete(self, title: str) -> None:
        """One more gate: the title, typed back, is the confirmation the
        API requires too."""
        typed = FormTextField(label="Title", hint=title)
        dialog: StyledAlertDialog | None = None

        async def _do_delete() -> None:
            if self._doc is None:
                return
            code, body = await self._api().request_with_status(
                "DELETE", f"{API}/{self._doc['id']}", params={"confirm": typed.value}
            )
            if code != 204:
                detail = body.get("detail") if isinstance(body, dict) else None
                ErrorSnackBar(str(detail or "The title did not match.")).launch(
                    self.page
                )
                return
            if dialog is not None:
                dialog.open = False
            self.clear()
            await self._on_change()

        dialog = StyledAlertDialog(
            title="Delete protected document?",
            body=ft.Column(
                [
                    SecondaryText(
                        f'Type "{title}" to retire it. The stored file is kept.',
                        size=Theme.Typography.BODY_SMALL,
                    ),
                    typed,
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_do_delete,
                    text="Delete",
                    variant="stop",
                    compact=True,
                )
            ],
            width=420,
        )
        self.page.open(dialog)
