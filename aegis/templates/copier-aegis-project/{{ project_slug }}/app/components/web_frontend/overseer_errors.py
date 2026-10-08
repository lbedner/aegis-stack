"""Overseer > Errors: retained errors grouped by cause, one issue's
occurrences in a drawer, the list kept current over SSE (one reader per
viewer, reloading only when something changed)."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
import time
from typing import Any

from pydantic import BaseModel

from app.core.config import settings
from app.core.formatting import format_relative_time
from app.services.system import ui_errors, ui_logs
from app.services.system.errors.client import repository, unavailable_reason
from app.services.system.errors.models import ErrorIssue
from app.services.system.errors.store import StoreUnavailableError
from app.services.system.models import ComponentStatus
from app.services.system.redis_keys import decoded

from .overseer_live import changed_frames, frame, heartbeat
from .overseer_logs import picker
from .overseer_nav import NavItem, SectionRequest, runtime_page_url
from .rendering import drawer_state, fragment, pager, with_query

SECTIONS = ((None, {"overview": "Errors"}),)
ITEM = NavItem(
    "errors",
    "errors",
    "Errors",
    "/overseer/errors",
    "",
    ComponentStatus(name="errors", message=""),
)
PATH = "/overseer/errors"
DETAIL = "/partials/overseer/errors/detail"
EVENTS = "/overseer/events/errors"
EVENT = "errors-results"
RECONCILE_SECONDS = 15
ROWS = "pages/overseer/errors/_rows.html"
# The filters a query carries, one value each, then the pickers' lists.
FILTERS = ("level", "window", "q")
PICKS = ("service", "container", "app_service")


class ErrorCell(BaseModel):
    type: str
    message: str
    url: str


class SourceCell(BaseModel):
    service: str
    runtime: str


class ErrorRow(BaseModel):
    """One issue as the table shows it."""

    id: str
    error: ErrorCell
    source: SourceCell
    count: int
    first_seen: datetime
    last_seen: datetime


def parameters(query: Mapping[str, str]) -> dict[str, str | list[str]]:
    """The list's filters, which every link and the stream carry."""
    return {key: query.get(key, "") for key in FILTERS} | {
        key: ui_logs.listed(query, key) for key in PICKS
    }


def labels(sources: list[dict[str, Any]]) -> dict[str, str]:
    """Each container's runtime as the Logs picker names it (``Worker ·
    system`` for one of several), by container name."""
    return {
        c["name"]: f"{s['title']} · {c['label']}"
        for s in sources
        for c in s["containers"]
    }


def row(issue: ErrorIssue, query: Mapping[str, str], names: dict[str, str]) -> ErrorRow:
    url = with_query(
        PATH, **parameters(query), issue=issue.fingerprint, occurrence=issue.latest_id
    )
    return ErrorRow(
        id=issue.fingerprint,
        error=ErrorCell(
            type=issue.exception_type or "Error", message=issue.message, url=url
        ),
        source=SourceCell(
            service=issue.app_service or "Unattributed",
            runtime=names.get(issue.container_name or "")
            or ui_logs.title_of(issue.page),
        ),
        count=issue.count,
        first_seen=issue.first_seen,
        last_seen=issue.last_seen,
    )


def list_context(
    context: dict[str, Any], query: Mapping[str, str], names: dict[str, str]
) -> dict[str, Any]:
    """What the list (``_rows.html``) shows: rows, pager, the collector."""
    return context | {
        "error_rows": [row(issue, query, names) for issue in context["error_rows"]],
        "error_pager": pager(
            PATH,
            ui_errors.page_of(query),
            ui_errors.PAGE_SIZE,
            context["error_total"],
            **parameters(query),
        ),
        "error_time": format_relative_time,
        "error_max_occurrences": settings.ERROR_TRACKING_MAX_OCCURRENCES,
        "error_retention_days": round(
            settings.ERROR_TRACKING_RETENTION_SECONDS / 86400, 2
        ),
    }


def render(
    context: dict[str, Any], query: Mapping[str, str], names: dict[str, str]
) -> str:
    return fragment(ROWS, **list_context(context, query, names))


def detail(context: dict[str, Any], query: Mapping[str, str]) -> str:
    """One issue's occurrences in the drawer, paged on ``history_page``."""
    issue = query.get("issue", "")

    def url(**values: str) -> str:
        return with_query(PATH, **parameters(query), issue=issue, **values)

    shown = context["error_detail"]
    return fragment(
        "pages/overseer/errors/_detail.html",
        **context,
        error_url=url,
        error_history_pager=pager(
            PATH,
            ui_errors.page_of(query, "history_page"),
            ui_errors.PAGE_SIZE,
            context["error_history_total"],
            param="history_page",
            **parameters(query),
            issue=issue,
        ),
        error_logs_url=with_query(runtime_page_url(shown.page) + "/logs", window="3600")
        if shown
        else None,
    )


async def _sources() -> list[dict[str, Any]]:
    return ui_logs.sources(await ui_logs.containers())


async def list_fragment(query: Mapping[str, str]) -> str:
    return render(await ui_errors.load(query), query, labels(await _sources()))


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    sources = await _sources()
    drawer = (
        with_query(
            DETAIL,
            **parameters(req.query),
            **{
                key: req.query.get(key, "")
                for key in ("issue", "occurrence", "history_page")
            },
        )
        if req.query.get("issue")
        else None
    )
    shown = list_context(await ui_errors.load(req.query), req.query, labels(sources))
    return (
        shown
        | drawer_state("issue", drawer)
        | {
            "error_query": parameters(req.query),
            "error_service_options": picker(sources, req.query),
            "error_events": with_query(EVENTS, **parameters(req.query)),
            "section_subtitle": "Grouped errors retained from your containers. Click an issue to inspect its occurrences.",
        }
    )


async def updates(query: Mapping[str, str]) -> AsyncIterator[str]:
    """The list again whenever an error arrives or retention drops some,
    and every ``RECONCILE_SECONDS`` for its relative times."""
    names = labels(await _sources())
    if reason := unavailable_reason():
        yield frame(EVENT, render(ui_errors.empty("disabled", reason), query, names))
        return
    store = repository()
    sent: dict[str, str] = {}
    try:
        latest = await store.call("xrevrange", store.notifications, count=1)
        cursor = decoded(latest[0][0]) if latest else "0-0"
        context: dict[str, Any] = {}
        version: tuple[int, str] | None = None
        arrived = True
        while True:
            now = await store.version()
            if arrived or now != version:
                context = ui_errors.DEFAULTS | await ui_errors.load_list(store, query)
                version = now
            for out in changed_frames(sent, {EVENT: render(context, query, names)}):
                yield out
            arrived = False
            until = time.monotonic() + RECONCILE_SECONDS
            while not arrived and time.monotonic() < until:
                entries = await store.call(
                    "xread", {store.notifications: cursor}, count=256, block=1000
                )
                if entries:
                    arrived = True
                    cursor = decoded(entries[-1][1][-1][0])
                    await asyncio.sleep(0.25)  # coalesce a burst into one reload
    except StoreUnavailableError:
        yield frame(
            EVENT,
            render(ui_errors.empty("degraded", ui_errors.UNREADABLE), query, names),
        )
    finally:
        await store.client.aclose()


def events(query: Mapping[str, str]) -> AsyncIterator[str]:
    return heartbeat(updates(query))
