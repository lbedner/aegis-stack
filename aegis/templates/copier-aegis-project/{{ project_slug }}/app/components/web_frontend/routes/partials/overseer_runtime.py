"""The streams of the runtime sections (Container, ``overseer_container``,
and Logs, ``overseer_logs``) on every page with a container behind it, and
of Overseer > Logs.
Mounted by ``routes/pages.py`` behind the admin-only Overseer gate."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.components.web_frontend import overseer_container, overseer_logs
from app.components.web_frontend.overseer_live import event_stream
from app.core import runtime, series

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
