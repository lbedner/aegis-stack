"""Fragments for the Overseer Server page: one connection's timeline in
the drawer, and starting a load test. Mounted by ``routes/pages.py``."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_connections, overseer_server_load_tests
from app.components.web_frontend.rendering import dialog, form_fields, toast_response

router = APIRouter(prefix=overseer_connections.PARTIALS)


@router.get("/{record_id}/drawer", response_class=HTMLResponse)
async def connection_drawer(request: Request, record_id: str) -> Response:
    context = await overseer_connections.drawer_context(record_id)
    if context is None:
        raise HTTPException(
            status_code=404, detail="That connection is no longer remembered."
        )
    return dialog(request, "pages/overseer/server/_connection_drawer.html", **context)


load_tests_router = APIRouter(prefix=overseer_server_load_tests.PARTIALS)


@load_tests_router.post("")
async def start_load_test(request: Request) -> Response:
    """Start a run against one of the app's routes; the list streams it."""
    job_id, why = await overseer_server_load_tests.start(
        await form_fields(request), request.app
    )
    if job_id is None:
        return toast_response(f"Load test not started: {why}", "error")
    return toast_response("Load test started")
