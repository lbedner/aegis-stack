"""Overseer > Deployments' actions (``overseer_deploy_actions``): each asks
``aegis deploy-agent`` for one, audited (refused ones too), and answers
with the job it started, which the card's stream then follows. Mounted by
``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.backend.api.utils import audit_admin_action
from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import RefusedError
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


@router.get(actions.catalog_url("{provider}"), response_class=HTMLResponse)
async def provision_form(
    request: Request, provider: str, actor: Actor = Depends(overseer_actor)
) -> HTMLResponse:
    """A provider's new-server form, from its catalog; the agent asked for
    the catalog when there is none (a read: not audited)."""
    form = dict(request.query_params)
    try:
        page = await actions.render_provision_form(provider, form, actor.label)
    except RefusedError:  # not a provider servers are created on from here
        raise HTTPException(status_code=404) from None
    return HTMLResponse(page)


@router.get(f"{actions.PARTIALS}/fit/{{provider}}", response_class=HTMLResponse)
async def fit(
    request: Request, provider: str, actor: Actor = Depends(overseer_actor)
) -> HTMLResponse:
    """Whether the size picked has room for the stack; the agent asked to
    measure it when it has not (a read: not audited)."""
    form = dict(request.query_params)
    try:
        page = await actions.render_fit(provider, form, actor.label)
    except RefusedError:  # not a provider servers are created on from here
        raise HTTPException(status_code=404) from None
    return HTMLResponse(page)


@router.post(f"{actions.PARTIALS}/{{action}}", response_class=HTMLResponse)
async def ask(
    request: Request,
    action: str,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Ask the deploy agent for ``action``; the answer is its job."""
    if action not in actions.TITLES:
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
