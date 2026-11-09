"""Overseer > Deployments' actions (``overseer_deploy_actions``): each asks
``aegis deploy-agent`` for one, audited (refused ones too), and answers
with the job it started, which the card's stream then follows; and the
DNS section's changes, made at the registrar (``ops.dns``). Mounted by
``routes/pages.py`` behind Overseer's gate (``overseer_access``)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
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
    dialog,
    form_fields,
    form_number,
    fragment,
    go_to,
    toast_response,
    with_toast,
)
from app.core.audit import AuditEmitter, get_audit
from app.services.ops import dns
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


RECORD_FORM = "pages/overseer/deployments/_dns_record.html"


def _record_form(
    request: Request,
    record_id: str | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
    **values: str,
) -> Response:
    """A record's form in the dialog: a new one, or ``record_id``'s edit,
    holding ``values``; a 422 again with its ``errors``."""
    url = overseer_deployments.DNS_RECORDS
    values = {"ttl": str(dns.TTL)} | values
    types = overseer_deployments.DNS_TYPES
    if (kind := values.get("type")) and kind not in [t["id"] for t in types]:
        types = [*types, {"id": kind, "name": kind}]  # a record's own: kept
    return dialog(
        request,
        RECORD_FORM,
        status_code,
        action=f"{url}/{record_id}" if record_id else url,
        editing=record_id is not None,
        domain=dns.domain(),
        server_ip=dns.server_ip(),
        ttl_floor=dns.TTL,
        prioritized=" and ".join(sorted(dns.PRIORITIZED)),
        types=types,
        values=values,
        errors=errors or [],
    )


@router.get(f"{overseer_deployments.DNS_RECORDS}/new", response_class=HTMLResponse)
async def new_record(request: Request) -> Response:
    return _record_form(request)


@router.get(
    f"{overseer_deployments.DNS_RECORDS}/{{record_id}}/edit",
    response_class=HTMLResponse,
)
async def edit_record_form(request: Request, record_id: str) -> Response:
    r = await _record(record_id)
    return _record_form(request, record_id, **dns.fields(r))


async def _save(
    request: Request,
    actor: Actor,
    audit: AuditEmitter,
    record_id: str | None,
    form: dict[str, str],
) -> Response:
    """Add a record on the domain (the registrar's add is idempotent), or
    change ``record_id``'s in place; then show the section again. A
    refusal brings the form back, saying why."""
    event = "deploy.dns_edit" if record_id else "deploy.dns_set"
    apex = dns.domain()
    try:
        record = dns.record(
            form["host"],
            form["type"],
            form["value"],
            form_number(form["ttl"], "TTL") or dns.TTL,
            form_number(form["priority"], "Priority"),
        )
        if record_id:
            await dns.registrar().edit_dns_record(apex, record_id, record)
        else:
            await dns.registrar().create_dns_records(apex, [record])
    except Exception as exc:  # noqa: BLE001 - the form says why
        outcome = "refused" if isinstance(exc, ValueError) else "failed"
        await audit_admin_action(audit, actor, request, event, outcome, str(exc))
        return _record_form(request, record_id, [str(exc)], 422, **form)
    verb = "Changed" if record_id else "Added"
    said = f"{verb} {record.type} {dns.label(record.host, apex)} → {record.value}"
    await audit_admin_action(audit, actor, request, event, "requested", said)
    return go_to(overseer_deployments.DNS_URL, said, "#overseer-main")


def _record_fields(
    host: Annotated[str, Form()],
    type_: Annotated[str, Form(alias="type")] = "A",
    value: Annotated[str, Form()] = "",
    ttl: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
) -> dict[str, str]:
    """A record's form as typed, for ``_save`` (and to hold on a 422)."""
    return {
        "host": host,
        "type": type_,
        "value": value,
        "ttl": ttl,
        "priority": priority,
    }


@router.post(overseer_deployments.DNS_RECORDS)
async def add_record(
    request: Request,
    form: dict[str, str] = Depends(_record_fields),
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    return await _save(request, actor, audit, None, form)


@router.post(f"{overseer_deployments.DNS_RECORDS}/{{record_id}}")
async def edit_record(
    request: Request,
    record_id: str,
    form: dict[str, str] = Depends(_record_fields),
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    await _record(record_id)  # 404 where it is gone
    return await _save(request, actor, audit, record_id, form)


async def _record(record_id: str) -> Any:
    """The domain's record ``record_id``: 404 where it is gone, 502 with
    the reason where the registrar did not answer (no keys, say)."""
    apex = dns.domain()
    try:
        found = await dns.registrar().list_dns_records(apex) if apex else []
    except Exception as exc:  # noqa: BLE001 - the toast says why
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    for r in found:
        if r.provider_id == record_id:
            return r
    raise HTTPException(status_code=404, detail="That record is gone.")


@router.get(
    f"{overseer_deployments.DNS_RECORDS}/{{record_id}}/confirm-delete",
    response_class=HTMLResponse,
)
async def confirm_delete_record(request: Request, record_id: str) -> Response:
    r = await _record(record_id)
    # A wildcard only answers for names with no record of their own.
    body = (
        "Subdomains without their own record stop resolving."
        if r.host.startswith("*")
        else f"It stops pointing at {r.value}."
    )
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete {r.type} {dns.label(r.host, dns.domain())}?",
        body=body,
        url=f"{overseer_deployments.DNS_RECORDS}/{r.provider_id}",
        label="Delete",
        method="delete",
        done="Record deleted",
    )


@router.delete(f"{overseer_deployments.DNS_RECORDS}/{{record_id}}", status_code=204)
async def delete_record(
    request: Request,
    record_id: str,
    actor: Actor = Depends(overseer_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Response:
    r = await _record(record_id)
    event, apex = "deploy.dns_delete", dns.domain()
    said = f"Deleted {r.type} {dns.label(r.host, apex)} → {r.value}"
    try:
        await dns.registrar().delete_dns_record(apex, r.provider_id)
    except Exception as exc:  # noqa: BLE001 - the dialog's toast says why
        await audit_admin_action(audit, actor, request, event, "failed", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await audit_admin_action(audit, actor, request, event, "requested", said)
    return Response(status_code=204)
