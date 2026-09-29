"""Every extraction, running or finished, in one live table.

Rows come from the jobs API, which knows every job whether it ran here
or on a worker, so kicking off five extractions shows five rows moving.
One SSE feed keeps the table current; nothing here polls a document.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import DataTable, DataTableColumn, SecondaryText
from app.components.frontend.controls.busy_bar import busy_bar
from app.components.frontend.controls.jobs import follow_jobs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.documents.domains.extraction.activity import (
    ActivityRow,
    activity_rows,
    document_id_of,
)

from .documents_pages import API
from .modal_sections import EmptyStatePlaceholder, status_dot


class ActivityTab(ft.Container):
    """The live table. ``on_finished`` fires with the document id when one
    of its jobs lands, so the pane showing that document can refresh."""

    def __init__(
        self,
        page: ft.Page,
        *,
        on_finished: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self.page = page
        self._on_finished = on_finished
        self._jobs: dict[str, dict[str, Any]] = {}
        self._titles: dict[int, str] = {}
        self._table = ft.Container(
            content=EmptyStatePlaceholder(
                "Nothing running. Extract a document to see it here."
            ),
            expand=True,
        )
        self.content = ft.Column([self._table], expand=True)
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self.load)
        page.run_task(self._follow)

    def _api(self) -> Any:
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self.page).api_client

    async def load(self) -> None:
        api = self._api()
        docs = await api.get(
            API, params={"page_size": 200, "include_superseded": "true"}
        )
        items = docs.get("items") if isinstance(docs, dict) else None
        self._titles = {
            int(d["id"]): str(d.get("title") or "") for d in (items or []) if "id" in d
        }
        jobs = await api.get("/api/v1/jobs")
        self._jobs = {
            str(j["job_id"]): j for j in (jobs if isinstance(jobs, list) else [])
        }
        self._render()

    async def _follow(self) -> None:
        await follow_jobs(self._api(), on_snapshot=self._on_snapshot)

    def _on_snapshot(self, snapshot: dict[str, Any]) -> None:
        job_id = str(snapshot.get("job_id"))
        before = self._jobs.get(job_id, {}).get("status")
        self._jobs[job_id] = snapshot
        self._render()
        document_id = document_id_of(snapshot)
        if (
            before == "running"
            and snapshot.get("status") != "running"
            and document_id is not None
            and self._on_finished is not None
        ):
            self.page.run_task(self._on_finished, document_id)

    def _render(self) -> None:
        rows = activity_rows(list(self._jobs.values()), self._titles)
        if not rows:
            self._table.content = EmptyStatePlaceholder(
                "Nothing running. Extract a document to see it here."
            )
        else:
            self._table.content = DataTable(
                columns=[
                    DataTableColumn("Document", width=320, style="primary"),
                    DataTableColumn("Status", width=340),
                    DataTableColumn("When", width=120, style="secondary"),
                ],
                rows=[[row.title, self._status_cell(row), row.when] for row in rows],
                scroll_height=600,
            )
        if self._table.page is not None:
            self._table.update()

    @staticmethod
    def _status_cell(row: ActivityRow) -> ft.Control:
        """One column, because one column is all there is to say.

        The state and the sentence describing it are the same fact: a bar
        beside "Reading page 2 of 5" says everything a Detail column would
        have repeated, and a queued job has nothing to add to the word
        "Queued".
        """
        if row.stalled:
            # Long enough that a worker should have taken it and none has.
            return status_dot("Waiting", Theme.Colors.WARNING, row.detail)
        if row.queued:
            # The bar is a claim that work is under way. Nothing is under
            # way until a worker says so.
            return status_dot("Queued", Theme.Colors.TEXT_SECONDARY, row.detail)
        if row.running:
            return ft.Row(
                [
                    busy_bar(width=80),
                    SecondaryText(row.detail, size=Theme.Typography.BODY_SMALL),
                ],
                spacing=Theme.Spacing.XS,
                tight=True,
            )
        if row.failed:
            return status_dot("Failed", Theme.Colors.ERROR, row.detail)
        if row.incomplete:
            return status_dot(row.detail, Theme.Colors.WARNING, row.detail)
        return status_dot(row.detail, Theme.Colors.ACCENT, row.detail)
