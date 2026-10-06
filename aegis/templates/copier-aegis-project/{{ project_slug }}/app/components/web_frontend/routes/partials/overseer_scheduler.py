"""Fragments for the Overseer Scheduler page: the Run Now confirmation.

Its button calls the scheduler API itself (``POST .../jobs/{id}/run``), as
Flet does, so the API keeps its guard and its already-running check. Mounted
by ``routes/pages.py`` at ``overseer_scheduler.PARTIALS``.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_scheduler
from app.components.web_frontend.overseer_nav import find_installed
from app.components.web_frontend.rendering import dialog
from app.core.constants import ComponentName

router = APIRouter(prefix=overseer_scheduler.PARTIALS)


@router.get("/confirm/run/{job_id}", response_class=HTMLResponse)
async def confirm_run(request: Request, job_id: str) -> Response:
    """Confirm running one scheduled job now."""
    item = find_installed("components", ComponentName.SCHEDULER)
    task = (
        next(
            (
                t
                for t in overseer_scheduler.tasks(item.component.metadata or {})
                if t.get("job_id") == job_id
            ),
            None,
        )
        if item
        else None
    )
    if task is None:
        raise HTTPException(status_code=404)
    name = task.get("name") or job_id
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title="Run job now",
        body=f"Run {name} now? It runs in the background and is recorded in the history.",
        method="post",
        url=f"/api/v1/scheduler/jobs/{job_id}/run",
        label="Run",
        tone="primary",
        done=f"{name} started",
    )
