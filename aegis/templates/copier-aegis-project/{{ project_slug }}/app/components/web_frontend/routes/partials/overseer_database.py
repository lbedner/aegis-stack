"""The Database page's Transactions stream, and a Postgres connection's
End confirm, whose button calls the API that ends it (and audits it).
Mounted by ``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.web_frontend import overseer_database
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import dialog

router = APIRouter()


@router.get(overseer_database.EVENTS, include_in_schema=False)
async def transactions_events() -> StreamingResponse:
    """The open transactions over SSE."""
    return event_stream(overseer_database.events())


@router.get(overseer_database.END_CONFIRM, response_class=HTMLResponse)
async def confirm_end(request: Request, pid: int) -> Response:
    """Confirm ending one Postgres connection."""
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=overseer_database.END_TITLE,
        body=f"Connection {pid} closes, and its open transaction rolls back. "
        "The process that held it gets an error on its next statement.",
        method="post",
        url=overseer_database.END_API.format(pid=pid),
        label="End",
        tone="warn",
        done=f"Ended connection {pid}",
    )
