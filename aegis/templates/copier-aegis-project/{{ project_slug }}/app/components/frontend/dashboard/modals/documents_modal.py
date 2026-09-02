"""Documents service detail modal: the file cabinet, browsable.

Two tabs. Documents lists what is stored (filter by kind and tag, search
what you can see) beside a pane for the selected one, and takes uploads
through the same signed browser-upload endpoint chat attachments use.
Tags lists every label in use with its count.
"""

from __future__ import annotations

import mimetypes
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    NativeDropdown,
    PrimaryText,
    SecondaryText,
    ThemedSwitch,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.controls.uploads import BrowserUploads
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_bytes, format_date
from app.services.documents.models import DOCUMENT_KINDS
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .documents_detail_pane import API, CHANNELS, DocumentDetailPane
from .modal_sections import EmptyStatePlaceholder, row_matches

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


def _filter_dropdown(
    everything: str,
    options: list[tuple[str, str]],
    *,
    width: int,
    on_change: Any,
) -> NativeDropdown:
    """A toolbar filter: dense, unlabeled, first entry means no filter."""
    return NativeDropdown(
        value=ALL,
        options=[
            ft.dropdown.Option(key=ALL, text=everything),
            *[ft.dropdown.Option(key=k, text=t) for k, t in options],
        ],
        width=width,
        enable_filter=False,
        enable_search=False,
        on_change=on_change,
    )


def _title_cell(doc: dict[str, Any]) -> Any:
    """The title, with a lock beside it when the document is protected."""
    title = str(doc.get("title") or "-")
    if not doc.get("protected"):
        return title
    return ft.Row(
        [
            PrimaryText(title),
            ft.Icon(ft.Icons.LOCK_OUTLINE, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        tight=True,
        spacing=Theme.Spacing.XS,
    )


class DocumentsTab(ft.Container):
    """Listing, filters, upload, and the detail pane."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._docs: list[dict[str, Any]] = []
        self._query = ""
        self._kind = _filter_dropdown(
            "All kinds",
            [(k, k.title()) for k in DOCUMENT_KINDS],
            width=150,
            on_change=lambda _: page.run_task(self._load),
        )
        self._channel = _filter_dropdown(
            "Any channel",
            [(c, c.title()) for c in CHANNELS],
            width=150,
            on_change=lambda _: page.run_task(self._load),
        )
        self._tag = _filter_dropdown(
            "Any tag", [], width=170, on_change=lambda _: page.run_task(self._load)
        )
        self._replaced = ThemedSwitch(
            value=False, on_change=lambda _: page.run_task(self._load)
        )
        # The search takes whatever width the fixed filters leave, so the
        # row can never overrun the pane beside it.
        self._search = StyledTextField(
            compact=True,
            hint_text="Search title or tag",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            on_change=self._on_search,
        )
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Loading documents..."), expand=True
        )
        self._pane = DocumentDetailPane(page, on_change=self._load)
        self._uploads = BrowserUploads(on_file=self._file)
        self._uploads.mount(page)
        # One line: search, the three filters, then the switch and the one
        # primary action pushed to the right edge.
        toolbar = ft.Row(
            [
                self._search,
                self._kind,
                self._channel,
                self._tag,
                ft.Container(width=Theme.Spacing.SM),
                SecondaryText("Replaced", size=Theme.Typography.BODY_SMALL),
                self._replaced,
                PulseButton(on_click_callable=self._pick, text="Upload", compact=True),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
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
        if self._channel.value != ALL:
            params["channel"] = self._channel.value
        if self._replaced.value:
            params["include_superseded"] = "true"
        data = await api.get(API, params=params)
        items = data.get("items") if isinstance(data, dict) else None
        self._docs = items if isinstance(items, list) else []
        tags = await api.get(f"{API}/tags")
        labels = [str(t["label"]) for t in tags] if isinstance(tags, list) else []
        self._tag.options = [
            ft.dropdown.Option(key=ALL, text="Any tag"),
            *[ft.dropdown.Option(key=t, text=t) for t in labels],
        ]
        if self._tag.value not in {ALL, *labels}:
            self._tag.value = ALL
        if self._tag.page is not None:
            self._tag.update()
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
                _title_cell(doc),
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
            on_row_click=lambda i: self._pane.show(docs[i], others=self._docs),
        )
        if self.page:
            self._table.update()

    async def _pick(self) -> None:
        self._uploads.pick(dialog_title="Upload documents", allow_multiple=True)

    async def _file(self, name: str, data: bytes) -> None:
        """A picked file arrived on the server: hand it to the store."""
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
            width=1600,
            height=900,
            status_detail=get_status_detail(component_data),
        )
