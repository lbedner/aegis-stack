"""Overseer > Deployments' actions (``overseer_deploy_actions``): each asks
``aegis deploy-agent`` for one, audited (refused ones too), and answers
with the job it started, which the card's stream then follows. Mounted by
``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.backend.api.utils import audit_admin_action
from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import PROTOCOL, RefusedError
from app.components.web_frontend import overseer_deploy_actions as actions
from app.components.web_frontend.overseer_access import overseer_actor
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import (
    form_fields,
    toast_response,
    with_toast,
)
from app.core.audit import AuditEmitter, get_audit
from app.services.shared.deps import Actor

router = APIRouter()


@router.get(actions.EVENTS, include_in_schema=False)
async def job_events() -> StreamingResponse:
    """The newest deploy job, while the Deployments page is open."""
    return event_stream(actions.events())


@router.post(f"{actions.PARTIALS}/{{action}}", response_class=HTMLResponse)
async def ask(
    request: Request,
    action: str,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Ask the deploy agent for ``action``; the answer is its job."""
    if action not in PROTOCOL["actions"]:
        raise HTTPException(status_code=404)
    event = f"deploy.{action}"
    try:
        args = await actions.request_args(action, await form_fields(request))
        job_id = await deploy_agent.enqueue(action, args, actor.label)
    except RefusedError as exc:
        await audit_admin_action(audit, actor, request, event, "refused", str(exc))
        return toast_response(str(exc), "error")
    title = actions.TITLES[action]
    await audit_admin_action(
        audit, actor, request, event, "requested", title, job=job_id, **args
    )
    page = HTMLResponse(await actions.render_job(job_id))
    return with_toast(page, f"{title}: asked the deploy agent")
