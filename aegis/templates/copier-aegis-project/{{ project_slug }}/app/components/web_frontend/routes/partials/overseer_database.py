"""The Database page's Transactions stream; a Postgres connection's End
confirm, whose button calls the API that ends it (and audits it); and
Query's statement, run read-only and audited, refused ones too.
Mounted by ``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.backend.api.utils import audit_admin_action
from app.components.web_frontend import overseer_database, overseer_database_browser
from app.components.web_frontend.overseer_access import overseer_actor
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import dialog, form_fields, fragment
from app.core.audit import AuditEmitter, get_audit
from app.services.shared.deps import Actor

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


@router.post(overseer_database_browser.QUERY_RUN, response_class=HTMLResponse)
async def run_query(
    request: Request,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Run the prompt's statement read-only; the answer fills the scroller
    (not found where rows are hidden, unaudited: nothing ran)."""
    sql = (await form_fields(request)).get("sql", "")
    outcome, answer = await overseer_database_browser.query(sql)
    await audit_admin_action(audit, actor, request, "database.query", outcome, sql)
    return HTMLResponse(fragment(overseer_database_browser.QUERY_ANSWER, **answer))
