"""The Database page's Transactions stream; a Postgres connection's End
confirm, whose button calls the API that ends it (and audits it);
Query's statement, run read-only and audited, refused ones too; and a tab
saved for every admin, or a saved query deleted, each audited.
Mounted by ``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.backend.api.utils import audit_admin_action
from app.components.web_frontend import (
    overseer_database,
    overseer_database_browser,
    overseer_database_saved,
)
from app.components.web_frontend.overseer_access import overseer_actor
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import (
    dialog,
    form_fields,
    fragment,
    toast_response,
    trigger,
)
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


@router.get(overseer_database_saved.QUERY_SAVE, response_class=HTMLResponse)
async def saved_queries() -> Response:
    """The saved queries, as the Saved menu lists them when it opens and
    again after a save or a delete."""
    saved = await overseer_database_saved.saved_queries()
    return HTMLResponse(fragment(overseer_database_saved.QUERY_SAVED, **saved))


def _changed(note: str, done: bool) -> Response:
    """A save's or a delete's whole answer: its toast and, when it changed
    something, the Saved list told to read again."""
    response = toast_response(note, "ok" if done else "warn")
    return trigger(response, overseer_database_saved.REFRESH) if done else response


@router.post(overseer_database_saved.QUERY_SAVE)
async def save_query(
    request: Request,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Keep the tab's statement under its name for every admin (not found
    where rows are hidden)."""
    fields = await form_fields(request)
    name = fields.get("name", "")
    outcome, note = await overseer_database_saved.save_query(
        name, fields.get("sql", ""), actor.email
    )
    await audit_admin_action(
        audit, actor, request, "database.query_saved", outcome, name
    )
    return _changed(note, outcome == "saved")


@router.post(overseer_database_saved.QUERY_FORGET)
async def forget_query(
    request: Request,
    query_id: int,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Delete a saved query."""
    outcome, name, note = await overseer_database_saved.forget_query(query_id)
    await audit_admin_action(
        audit, actor, request, "database.query_forgotten", outcome, name
    )
    return _changed(note, outcome == "forgotten")
