"""Every extraction, running or finished, in one live table.

Rows come from the jobs API, which knows every job whether it ran here
or on a worker, so kicking off five extractions shows five rows moving.
One SSE feed keeps the table current; nothing here polls a document.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import flet as ft

from app.components.frontend.controls import DataTable, DataTableColumn, SecondaryText
from app.components.frontend.controls.busy_bar import busy_bar
from app.components.frontend.controls.jobs import follow_jobs
from app.components.frontend.theme import AegisTheme as Theme

from .documents_pages import API, extraction_summary
from .modal_sections import EmptyStatePlaceholder, status_dot

JOB_PREFIX = "documents-extract:"
# A job still "Queued..." this long has no worker picking it up; say so
# rather than showing a bar that moves and a word that does not.
QUEUED_TOO_LONG_SECONDS = 60


@dataclass
class ActivityRow:
    job_id: str
    document_id: int
    title: str
    detail: str
    running: bool
    failed: bool
    queued: bool
    stalled: bool
    incomplete: bool
    when: str
    started_at: str


def _document_id(job: dict[str, Any]) -> int | None:
    name = str(job.get("name") or "")
    if not name.startswith(JOB_PREFIX):
        return None
    try:
        return int(name[len(JOB_PREFIX) :])
    except ValueError:
        return None


def _is_queued(job: dict[str, Any]) -> bool:
    """Whether the job is still waiting: no worker has reported on it yet.

    The label is the report. Until one arrives it reads "Queued...", and a
    job nobody has picked up is not a job in progress, however long the
    store has been holding it open.
    """
    return str(job.get("label") or "Queued...").startswith("Queued")


def _started(job: dict[str, Any]) -> datetime | None:
    """When the job was created, or None when the record predates the field."""
    try:
        started = datetime.fromisoformat(str(job.get("started_at") or ""))
    except ValueError:
        return None
    return started if started.tzinfo else started.replace(tzinfo=UTC)


def age_label(started_at: str, now: datetime) -> str:
    """How long ago, in the coarsest unit that still says something.

    Relative rather than a clock time: the table renders on the server, so
    a printed hour would be the container's, not the reader's.
    """
    started = _started({"started_at": started_at})
    if started is None:
        return ""
    seconds = int((now - started).total_seconds())
    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _queued_for(job: dict[str, Any], now: datetime) -> int | None:
    """Seconds a job has sat queued, or None when that cannot be known."""
    if not _is_queued(job):
        return None
    started = _started(job)
    if started is None:
        return None
    return int((now - started).total_seconds())


def activity_rows(
    jobs: list[dict[str, Any]], titles: dict[int, str], *, now: datetime | None = None
) -> list[ActivityRow]:
    """Extraction jobs as rows: the document's title, and one sentence for
    where it is. Other services' jobs are not this tab's business."""
    now = now or datetime.now(UTC)
    rows: list[ActivityRow] = []
    for job in jobs:
        document_id = _document_id(job)
        if document_id is None:
            continue
        status = job.get("status")
        queued = False
        stalled = False
        incomplete = False
        if status == "running":
            detail = str(job.get("label") or "Queued...")
            queued = _is_queued(job)
            waited = _queued_for(job, now)
            if waited is not None and waited >= QUEUED_TOO_LONG_SECONDS:
                detail = f"Queued for {waited // 60}m, no worker has picked it up"
                stalled = True
        elif status == "done":
            result = job.get("result") or {}
            detail = extraction_summary(result)
            # Finished is not the same as done with it: a page a model
            # refused is left unread, and the run reports that quietly.
            incomplete = int(result.get("unread") or 0) > 0
        else:
            detail = str(job.get("error") or "Failed")
        rows.append(
            ActivityRow(
                job_id=str(job.get("job_id")),
                document_id=document_id,
                title=titles.get(document_id, f"Document {document_id}"),
                detail=detail,
                running=status == "running",
                failed=status == "failed",
                queued=queued,
                stalled=stalled,
                incomplete=incomplete,
                when=age_label(str(job.get("started_at") or ""), now),
                started_at=str(job.get("started_at") or ""),
            )
        )
    # Newest first: two runs of the same document are only tellable apart
    # by when they ran.
    rows.sort(key=lambda r: r.started_at, reverse=True)
    return rows


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
        document_id = _document_id(snapshot)
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
