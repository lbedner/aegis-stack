"""The streams of the runtime sections (Container, ``overseer_container``,
and Logs, ``overseer_logs``) on every page with a container behind it, of
Overseer > Logs and of Overseer > Resources; and a container row's Restart confirm.
Mounted by ``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.web_frontend import (
    overseer_container,
    overseer_logs,
    overseer_resources,
)
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import dialog
from app.core import runtime, series
from app.services.system import ui_runtime

router = APIRouter()


def _known(page: str) -> None:
    if page not in runtime.PAGES:
        raise HTTPException(status_code=404)


@router.get(overseer_container.EVENTS, include_in_schema=False)
async def container_events(page: str, window: str | None = None) -> StreamingResponse:
    """The page's containers over SSE, charted over the window its range
    chips chose."""
    _known(page)
    return event_stream(overseer_container.events(page, series.window_of(window)))


@router.get(overseer_container.GLANCE_EVENTS, include_in_schema=False)
async def glance_events(page: str) -> StreamingResponse:
    """The glance above the page's Overview over SSE."""
    _known(page)
    return event_stream(overseer_container.glance_events(page))


@router.get(overseer_logs.EVENTS, include_in_schema=False)
async def logs_events(page: str, request: Request) -> StreamingResponse:
    """The page's new log lines over SSE, through its level and text
    filters."""
    _known(page)
    return event_stream(overseer_logs.events(page, request.query_params))


@router.get(overseer_logs.EVERY_EVENTS, include_in_schema=False)
async def every_logs_events(request: Request) -> StreamingResponse:
    """Overseer > Logs' new lines over SSE, through its service, level and
    text filters."""
    return event_stream(overseer_logs.everything_events(request.query_params))


@router.get(overseer_container.OVERVIEW_EVENTS, include_in_schema=False)
async def overview_events(
    view: str | None = None, zoom: str | None = None
) -> StreamingResponse:
    """Overseer's home: every page's glance over SSE, in its view (and
    zoom)."""
    return event_stream(overseer_container.overview_events(view, zoom))


@router.get(overseer_resources.EVENTS, include_in_schema=False)
async def resources_events(window: str | None = None) -> StreamingResponse:
    """Overseer > Resources over SSE, charted over the window its range
    chips chose."""
    return event_stream(overseer_resources.events(series.window_of(window)))


@router.get(overseer_container.RESTART, response_class=HTMLResponse)
async def confirm_restart(request: Request, name: str) -> Response:
    """Confirm restarting one of this app's containers; the button calls the
    restart API, which audits it."""
    own = runtime.is_own(await runtime.mine(name))  # errors: backend/main.py
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=ui_runtime.RESTART_TITLE,
        body=ui_runtime.restart_confirm(name, own),
        method="post",
        url=ui_runtime.RESTART_API.format(name=name),
        label="Restart",
        tone="warn",
        done=ui_runtime.restart_done(name, own),
    )
