"""What the detail pane's footer does: extract, download, retire.

Each of these is a decision about a document rather than a piece of the
form the pane renders, and each carries its own confirmation, wording and
failure handling. Kept beside the pane rather than inside it, so the pane
is what it says it is: the selected document, editable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    FormTextField,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.theme import AegisTheme as Theme

from .documents_pages import API, has_unread_pages


def extract_label(force: bool) -> str:
    """What the button says it will do."""
    return "Force extract" if force else "Extract"


def extract_tooltip(force: bool) -> str | None:
    return "Extract every page again with the current model" if force else None


def sync_extract_button(button: PulseButton, rows: list[dict[str, Any]]) -> bool:
    """Point the button at the run that is worth making; returns ``force``.

    Plain Extract on a fully-read document does nothing - the run comes
    back "Already extracted". Re-running is still worth offering, since
    the model that reads a page can change, but as something asked for
    rather than something that happens by pressing the same button.
    """
    force = not has_unread_pages(rows)
    button.text = extract_label(force)
    button.content = ft.Text(button.text, **asdict(button.text_style))
    button.tooltip = extract_tooltip(force)
    if button.page is not None:
        button.update()
    return force


async def start_extraction(
    page: ft.Page, api: Any, document: dict[str, Any], *, force: bool
) -> None:
    """Queue a read of the pages that need one and get out of the way.

    Progress lives on the Activity tab, one row per job, whether the job
    runs here or on a worker.
    """
    query = "background=true&force=true" if force else "background=true"
    started = await api.post(f"{API}/{document['id']}/extract?{query}")
    if not isinstance(started, dict) or not started.get("job_id"):
        ErrorSnackBar("Extraction could not start.").launch(page)
        return
    title = str(document.get("title") or "document")
    SuccessSnackBar(f"Extracting {title}. Follow it on the Activity tab.").launch(page)


def download(page: ft.Page, document: dict[str, Any]) -> None:
    """The original bytes, through the content route."""
    page.launch_url(f"{API}/{document['id']}/content")


def confirm_delete(
    page: ft.Page,
    api: Any,
    document: dict[str, Any],
    *,
    on_deleted: Callable[[], Awaitable[None]],
) -> None:
    """Retire a document, asking first - and asking harder when protected."""
    title = str(document.get("title") or "this document")
    if document.get("protected"):
        _confirm_protected_delete(page, api, document, title, on_deleted=on_deleted)
        return

    async def _do_delete() -> None:
        await api.delete(f"{API}/{document['id']}")
        await on_deleted()

    ConfirmDialog(
        page=page,
        title="Delete document?",
        message=f'"{title}" will be retired from the list. The stored file is kept.',
        confirm_text="Delete",
        destructive=True,
        on_confirm=_do_delete,
    ).show()


def _confirm_protected_delete(
    page: ft.Page,
    api: Any,
    document: dict[str, Any],
    title: str,
    *,
    on_deleted: Callable[[], Awaitable[None]],
) -> None:
    """One more gate: the title, typed back, is the confirmation the API
    requires too."""
    typed = FormTextField(label="Title", hint=title)
    dialog: StyledAlertDialog | None = None

    async def _do_delete() -> None:
        code, body = await api.request_with_status(
            "DELETE", f"{API}/{document['id']}", params={"confirm": typed.value}
        )
        if code != 204:
            detail = body.get("detail") if isinstance(body, dict) else None
            ErrorSnackBar(str(detail or "The title did not match.")).launch(page)
            return
        if dialog is not None:
            dialog.open = False
        await on_deleted()

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
    page.open(dialog)
