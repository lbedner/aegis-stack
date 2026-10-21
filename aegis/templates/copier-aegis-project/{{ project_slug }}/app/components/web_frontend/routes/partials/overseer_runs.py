"""A run's log and its stream (``overseer_runs``), for any Overseer row
that started a run. Mounted by ``routes/pages.py`` behind Overseer's gate
(``overseer_access``)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.components.web_frontend import overseer_runs
from app.components.web_frontend.overseer_live import event_stream

router = APIRouter(prefix=overseer_runs.PARTIALS)


@router.get("/{run_id}/log", response_class=HTMLResponse, include_in_schema=False)
async def run_log(run_id: str, live: bool = False) -> HTMLResponse:
    """The run's lines so far; following the rest while it is on. An
    unreachable store is a 503, as any unreachable runtime is."""
    try:
        return HTMLResponse(overseer_runs.render_box(run_id, live))
    except OSError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{run_id}/log/events", include_in_schema=False)
async def run_log_events(run_id: str) -> StreamingResponse:
    """The run's lines again whenever more were written."""
    return event_stream(overseer_runs.events(run_id))
