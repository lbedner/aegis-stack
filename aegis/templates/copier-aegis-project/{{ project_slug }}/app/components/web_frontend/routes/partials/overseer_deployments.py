"""Overseer > Deployments' actions (``overseer_deploy_actions``): each asks
``aegis deploy-agent`` for one, audited (refused ones too), and answers
with the job it started, which the card's stream then follows. Mounted by
``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.components.backend.api.utils import audit_admin_action
from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import RefusedError
from app.components.web_frontend import overseer_deploy_actions as actions
from app.components.web_frontend import overseer_deploy_form as deploy_form
from app.components.web_frontend import overseer_deployments
from app.components.web_frontend.overseer_access import overseer_actor
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import (
    form_fields,
    fragment,
    go_to,
    toast_response,
    with_toast,
)
from app.core.audit import AuditEmitter, get_audit
from app.services.shared.deps import Actor
from app.services.system import hosting, ui_deployments

router = APIRouter()


@router.get(actions.EVENTS, include_in_schema=False)
async def job_events(
    job: str | None = Query(None, pattern="^[0-9a-f]{32}$"),
    whole: bool = False,
) -> StreamingResponse:
    """A deploy job while a Deployments page shows it: the newest, as the
    card does or ``whole`` (New server), or the one Jobs picked (``job``)."""
    return event_stream(actions.events(job, whole=whole))


def _provisionable(provider: str) -> hosting.Provider:
    """The provider in the path, if servers are created on it from here."""
    try:
        return deploy_form.provisionable(provider)
    except RefusedError:
        raise HTTPException(status_code=404) from None


@router.get(
    deploy_form.panel_path("{panel}", "{provider}"), response_class=HTMLResponse
)
async def panel(
    request: Request,
    panel: str,
    # Refused before anything is looked up (``operator_refusal``).
    actor: Actor = Depends(overseer_actor),
    chosen: hosting.Provider = Depends(_provisionable),
) -> Response:
    """A part of the new-server form (``PANELS``: the form from the
    provider's catalog, whether it fits, what the account runs); the agent
    asked for what it needs when it has not (a read: not audited)."""
    if panel not in deploy_form.PANELS:
        raise HTTPException(status_code=404)
    form = dict(request.query_params)
    build, template, name = deploy_form.PANELS[panel]
    built = await build(chosen, form, actor.label)
    return _part(form, built, template, **{name: built})


@router.get(deploy_form.ROLLBACK, response_class=HTMLResponse)
async def rollback(
    request: Request, actor: Actor = Depends(overseer_actor)
) -> Response:
    """The backups a rollback picks from; the agent asked to list them when
    it has not (a read: not audited)."""
    form = dict(request.query_params)
    built = await deploy_form.rollback_panel(form, actor.label)
    return _part(form, built, deploy_form.ROLLBACK_TEMPLATE, r=built)


@router.get(deploy_form.HISTORY, response_class=HTMLResponse)
async def history(request: Request, actor: Actor = Depends(overseer_actor)) -> Response:
    """The server's deploy history; the agent asked to read it when it has
    not (a read: not audited)."""
    form = dict(request.query_params)
    built = await deploy_form.history_panel(form, actor.label)
    context = overseer_deployments.history_view(built)
    return _part(form, built, deploy_form.HISTORY_TEMPLATE, **context)


@router.get(deploy_form.LIVE, response_class=HTMLResponse)
async def live(request: Request, actor: Actor = Depends(overseer_actor)) -> Response:
    """What is live on the server (its newest deploy), from the history the
    agent reads (a read: not audited)."""
    form = dict(request.query_params)
    built = await deploy_form.history_panel(form, actor.label, deploy_form.LIVE)
    live = ui_deployments.live_facts(built.get("rows") or [])
    return _part(form, built, deploy_form.LIVE_TEMPLATE, live=built | {"live": live})


@router.get(deploy_form.STORAGE, response_class=HTMLResponse)
async def storage(request: Request, actor: Actor = Depends(overseer_actor)) -> Response:
    """How many stored files the server lacks, as the agent checks (a
    read: not audited)."""
    form = dict(request.query_params)
    built = await deploy_form.storage_panel(form, actor.label)
    return _part(form, built, deploy_form.STORAGE_TEMPLATE, storage=built)


def _part(
    form: dict[str, str], built: dict[str, Any], template: str, **context: Any
) -> Response:
    """A part the agent answers for (``built``), as the page asked for it.
    A poll still waiting gets no content: htmx swaps nothing, so the bar on
    the page keeps moving."""
    if "job" in form and built["state"] == "loading":
        return Response(status_code=204)
    return HTMLResponse(fragment(template, **context))


@router.post(f"{actions.PARTIALS}/{{action}}", response_class=HTMLResponse)
async def ask(
    request: Request,
    action: str,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    """Ask the deploy agent for ``action``; the answer is its job."""
    if not actions.asked_from_card(action):
        raise HTTPException(status_code=404)
    event = f"deploy.{action}"
    try:
        args = await deploy_form.request_args(action, await form_fields(request))
        job_id = await deploy_agent.enqueue(action, args, actor.label)
    except RefusedError as exc:
        await audit_admin_action(audit, actor, request, event, "refused", str(exc))
        return toast_response(str(exc), "error")
    title = actions.TITLES[action]
    await audit_admin_action(
        audit, actor, request, event, "requested", title, job=job_id, **args
    )
    said = f"{title}: asked the deploy agent"
    if action in actions.CREATING:  # New server follows it, whole
        return go_to(overseer_deployments.NEW_URL, said, "#overseer-main")
    return with_toast(HTMLResponse(await actions.render_job(job_id)), said)
