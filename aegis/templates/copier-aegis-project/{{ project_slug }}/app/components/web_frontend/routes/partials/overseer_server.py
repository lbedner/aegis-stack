"""Fragments for the Overseer Server page: one connection's timeline in
the drawer, a route's request form and its Execute, and starting a load
test. Mounted by ``routes/pages.py``."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import (
    overseer_connections,
    overseer_requests,
    overseer_server_load_tests,
)
from app.components.web_frontend.rendering import (
    dialog,
    form_fields,
    fragment,
    toast_response,
)

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


requests_router = APIRouter(prefix=overseer_requests.PARTIALS)


@requests_router.get("/form", response_class=HTMLResponse)
async def request_form(request: Request, route: str, mode: str = "try") -> Response:
    """A route's request form: to send once (Routes) or to load test."""
    op = overseer_requests.find(request.app.routes, route)
    if op is None:
        raise HTTPException(status_code=404, detail="No such route.")
    values = dict(request.query_params)
    context = (
        overseer_server_load_tests.form_context(op, values)
        if mode == overseer_requests.LOAD
        else overseer_requests.form_context(op, overseer_requests.TRY, values)
    )
    return HTMLResponse(fragment(overseer_requests.FORM, **context))


@requests_router.post("/execute", response_class=HTMLResponse)
async def execute(request: Request) -> Response:
    """Send the form's request once and show what came back."""
    answer, why = await overseer_requests.execute(
        await form_fields(request), request.app
    )
    if answer is None:
        return toast_response(f"Not sent: {why}", "error")
    return HTMLResponse(fragment(overseer_requests.ANSWER, answer=answer))
