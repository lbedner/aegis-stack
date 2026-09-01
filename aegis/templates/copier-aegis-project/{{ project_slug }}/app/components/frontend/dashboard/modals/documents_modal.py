"""Documents service detail modal: the file cabinet, browsable.

Two tabs. Documents lists what is stored (filter by kind and tag, search
what you can see) beside a pane for the selected one, and takes uploads
through the same signed browser-upload endpoint chat attachments use.
Tags lists every label in use with its count.
"""

from __future__ import annotations

import logging
import mimetypes
from typing import Any
from uuid import uuid4

import flet as ft

from app.components.frontend.controls import DataTable, DataTableColumn, FormDropdown
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.controls.uploads import signed_upload_url
from app.components.frontend.theme import AegisTheme as Theme
from app.core.constants import dashboard_upload_dir
from app.core.formatting import format_bytes, format_date
from app.services.documents.models import DOCUMENT_KINDS
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .documents_detail_pane import API, DocumentDetailPane
from .modal_sections import EmptyStatePlaceholder, row_matches

logger = logging.getLogger(__name__)

ALL = "all"


def display_date(doc: dict[str, Any]) -> str:
    """The letter's own date when it has one, else when it arrived."""
    return format_date(doc.get("document_date") or doc.get("received_at"))


def matching_documents(docs: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Search what the row shows: title and tags. Keys are not text."""
    return [
        doc
        for doc in docs
        if row_matches(query, [doc.get("title"), *doc.get("tags", [])])
    ]


class DocumentsTab(ft.Container):
    """Listing, filters, upload, and the detail pane."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._docs: list[dict[str, Any]] = []
        self._query = ""
        # Picker events name files by their local filename, and a scanner
        # batch can hold several with the same one, so each name keeps a
        # queue of server-side names rather than a single slot.
        self._uploads_in_flight: dict[str, list[str]] = {}
        self._kind = FormDropdown(
            label="Kind",
            value=ALL,
            width=150,
            options=[(ALL, "All"), *[(k, k.title()) for k in DOCUMENT_KINDS]],
            on_change=lambda _: page.run_task(self._load),
        )
        self._tag = FormDropdown(
            label="Tag",
            value=ALL,
            width=180,
            options=[(ALL, "All")],
            on_change=lambda _: page.run_task(self._load),
        )
        self._search = StyledTextField(
            compact=True, hint_text="Search", width=220, on_change=self._on_search
        )
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Loading documents..."), expand=True
        )
        self._pane = DocumentDetailPane(page, on_change=self._load)
        self._picker = ft.FilePicker(
            on_result=self._on_picked, on_upload=self._on_upload_progress
        )
        if self._picker not in page.overlay:
            page.overlay.append(self._picker)
        toolbar = ft.Row(
            [
                PulseButton(on_click_callable=self._pick, text="Upload", compact=True),
                self._kind,
                self._tag,
                self._search,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        # The pane sits beside toolbar AND table, so it starts at the top of
        # the tab and has the full height to show a document without scrolling.
        self.content = ft.Row(
            [
                ft.Column(
                    [toolbar, self._table], spacing=Theme.Spacing.MD, expand=True
                ),
                self._pane,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    def _api(self) -> Any:
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self.page).api_client

    async def _load(self) -> None:
        api = self._api()
        # ponytail: one page of 100, searched client-side; add paging when
        # a cabinet outgrows it.
        params: dict[str, Any] = {"page_size": 100}
        if self._kind.value != ALL:
            params["kind"] = self._kind.value
        if self._tag.value != ALL:
            params["tag"] = self._tag.value
        data = await api.get(API, params=params)
        items = data.get("items") if isinstance(data, dict) else None
        self._docs = items if isinstance(items, list) else []
        tags = await api.get(f"{API}/tags")
        labels = [str(t["label"]) for t in tags] if isinstance(tags, list) else []
        self._tag.set_options([(ALL, "All"), *[(t, t) for t in labels]])
        self._render()

    def _on_search(self, e: ft.ControlEvent) -> None:
        self._query = str(e.control.value or "")
        self._render()

    def _render(self) -> None:
        docs = matching_documents(self._docs, self._query)
        columns = [
            DataTableColumn("Title", width=260, style="primary"),
            DataTableColumn("Kind", width=110, style="secondary"),
            DataTableColumn("Date", width=110, style="secondary"),
            DataTableColumn("Size", width=90, style="secondary"),
            DataTableColumn("Tags", width=180, style="secondary"),
        ]
        rows = [
            [
                str(doc.get("title") or "-"),
                str(doc.get("kind") or "-").title(),
                display_date(doc) or "-",
                format_bytes(int(doc.get("byte_size") or 0)),
                ", ".join(doc.get("tags", [])) or "-",
            ]
            for doc in docs
        ]
        self._table.content = DataTable(
            columns=columns,
            rows=rows,
            scroll_height=600,
            empty_message="No documents yet",
            on_row_click=lambda i: self._pane.show(docs[i]),
        )
        if self.page:
            self._table.update()

    async def _pick(self) -> None:
        self._picker.pick_files(dialog_title="Upload documents", allow_multiple=True)

    def _on_picked(self, event: ft.FilePickerResultEvent) -> None:
        if not event.files:
            return
        uploads: list[ft.FilePickerUploadFile] = []
        for picked in event.files:
            name = picked.name or "document"
            server_name = f"{uuid4().hex}-{name}"
            self._uploads_in_flight.setdefault(name, []).append(server_name)
            uploads.append(
                ft.FilePickerUploadFile(name, upload_url=signed_upload_url(server_name))
            )
        self._picker.upload(uploads)

    def _on_upload_progress(self, event: ft.FilePickerUploadEvent) -> None:
        if event.error:
            self._take_upload(event.file_name)
            ErrorSnackBar(f"Upload failed: {event.error}").launch(self.page)
            return
        if (event.progress or 0) >= 1.0:
            self.page.run_task(self._file, event.file_name)

    def _take_upload(self, name: str) -> str | None:
        """The next server-side name queued under this local filename."""
        queue = self._uploads_in_flight.get(name)
        if not queue:
            return None
        server_name = queue.pop(0)
        if not queue:
            del self._uploads_in_flight[name]
        return server_name

    async def _file(self, name: str) -> None:
        """The upload arrived on the server: hand it to the store."""
        server_name = self._take_upload(name)
        if server_name is None:
            return
        path = dashboard_upload_dir() / server_name
        try:
            data = path.read_bytes()
        except OSError:
            logger.warning("documents.upload_missing name=%s", name)
            ErrorSnackBar(f"{name} did not arrive on the server.").launch(self.page)
            return
        finally:
            path.unlink(missing_ok=True)
        kind = self._kind.value if self._kind.value != ALL else "other"
        media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        code, body = await self._api().request_with_status(
            "POST",
            API,
            files={"file": (name, data, media_type)},
            form_data={"title": name, "kind": kind},
        )
        if code == 201:
            SuccessSnackBar(f"Stored {name}.").launch(self.page)
        elif code == 200 and isinstance(body, dict):
            SuccessSnackBar(
                f"{name} was already stored as {body.get('title')}."
            ).launch(self.page)
        else:
            detail = body.get("detail") if isinstance(body, dict) else None
            ErrorSnackBar(str(detail or f"Upload of {name} failed.")).launch(self.page)
        await self._load()


class TagsTab(ft.Container):
    """Every label in use, with how many documents wear it."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Loading tags..."), expand=True
        )
        self.content = ft.Column([self._table], expand=True)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        data = await get_session_state(self.page).api_client.get(f"{API}/tags")
        tags = data if isinstance(data, list) else []
        self._table.content = DataTable(
            columns=[
                DataTableColumn("Tag", width=300, style="primary"),
                DataTableColumn("Documents", width=120, style="secondary"),
            ],
            rows=[[str(t.get("label", "-")), str(t.get("count", 0))] for t in tags],
            scroll_height=600,
            empty_message="No tags yet. Select a document on the Documents tab to tag it.",
        )
        if self.page:
            self._table.update()


class DocumentsDetailDialog(BaseDetailPopup):
    """Detail modal for the documents service."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        tags_tab = TagsTab(page)

        def _on_tab_change(e: ft.ControlEvent) -> None:
            # Tags are added on the Documents tab; the counts must follow.
            if e.control.selected_index == 1:
                page.run_task(tags_tab._load)

        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Documents", content=DocumentsTab(page)),
                ft.Tab(text="Tags", content=tags_tab),
            ],
            expand=True,
            on_change=_on_tab_change,
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_documents"),
            subtitle_text=get_component_subtitle(
                "service_documents", component_data.metadata
            ),
            sections=[tabs],
            scrollable=False,
            width=1280,
            height=840,
            status_detail=get_status_detail(component_data),
        )
