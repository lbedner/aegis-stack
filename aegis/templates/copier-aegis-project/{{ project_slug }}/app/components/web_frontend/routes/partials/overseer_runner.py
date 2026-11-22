"""The Overseer Runner page's drawer: one run whole, read when its row is
opened. Mounted by ``routes/pages.py`` at ``overseer_runner.PARTIALS``
behind Overseer's gate."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.runner import runs
from app.components.web_frontend import overseer_runner
from app.components.web_frontend.overseer_access import Db, overseer_db
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import dialog

router = APIRouter(prefix=overseer_runner.PARTIALS)


@router.get("/{run_id}/drawer", response_class=HTMLResponse)
async def run_drawer(
    request: Request, run_id: int, db: Db = Depends(overseer_db)
) -> Response:
    context = await overseer_runner.drawer_context(db, run_id)
    if context is None:
        raise HTTPException(status_code=404, detail=overseer_runner.NO_RUN)
    return dialog(request, overseer_runner.DRAWER, **context)


@router.post("/{run_id}/push", response_class=HTMLResponse)
async def push_run(
    request: Request, run_id: int, db: Db = Depends(overseer_db)
) -> Response:
    """The run's branch asked to be pushed, and its drawer again, saying so."""
    run = await runs.one(db, run_id)
    if run is None or not run.branch:
        raise HTTPException(status_code=404, detail=overseer_runner.NO_RUN)
    pushed = await runs.push(db, run)
    context = await overseer_runner.drawer(db, run, pushed)
    return dialog(request, overseer_runner.DRAWER, **context)


@router.get("/{run_id}/events")
async def run_events(run_id: int) -> Response:
    """The drawer's live part, pushed as the run changes (``drawer_events``)."""
    return event_stream(overseer_runner.drawer_events(run_id))
