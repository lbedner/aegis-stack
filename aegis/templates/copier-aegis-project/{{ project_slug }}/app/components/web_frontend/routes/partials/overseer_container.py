"""The Container section's live table (``overseer_container``). Mounted by
``routes/pages.py`` behind the admin-only Overseer gate."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.components.web_frontend import overseer_container
from app.components.web_frontend.overseer_live import event_stream
from app.core import runtime, series

router = APIRouter()


@router.get(overseer_container.EVENTS, include_in_schema=False)
async def container_events(page: str, window: str | None = None) -> StreamingResponse:
    """The page's containers over SSE, while its Container section is open,
    charted over the window its range chips chose."""
    if page not in runtime.PAGES:
        raise HTTPException(status_code=404)
    return event_stream(overseer_container.events(page, series.window_of(window)))
