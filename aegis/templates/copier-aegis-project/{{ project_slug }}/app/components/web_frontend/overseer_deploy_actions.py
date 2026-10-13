"""Overseer > Deployments' actions: a new server (price, typed confirm,
provision), then deploy, back up, list backups, roll back and destroy.

Each is asked of ``aegis deploy-agent`` on the developer's machine through
the project's Redis (``app.components.deploy.agent``), so the SSH key
never enters the app, and comes back as its job, whose output the card
streams. A new server is offered on each provider whose token the app
holds (Overseer > Secrets, or ``.env``) or the agent does (its own
environment). Offered on the dev build only: a deployed server is
redeployed from the dev Overseer or CI. The htmx Overseer only; the Flet
dashboard shows the commands.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import PROTOCOL, RefusedError, validate
from app.core.config import settings
from app.core.log import logger
from app.services.system import hosting

from . import overseer_secrets
from .overseer_live import fragment_events
from .rendering import fragment

EVENTS = "/overseer/events/deployments/job"
EVENT = "deploy-job"
PARTIALS = "/partials/overseer/deployments"
JOB = "pages/overseer/deployments/_job.html"
INTERVAL_SECONDS = 1.0
AGENT_COMMAND = "aegis deploy-agent"
CD_COMMAND = "aegis deploy-cd-setup"
LIVE = ("provisioning", "ready")  # a provision record whose resources may exist
TITLES = {
    "quote": "Price",
    "provision": "New server",
    "deploy": "Deploy",
    "backup": "Back up",
    "backups": "Backups",
    "rollback": "Roll back",
    "destroy": "Destroy",
}
DEPLOYED = "This is a deployed server: deploy from the dev Overseer or CI."


def _deployed() -> bool:
    return settings.BUILD_ID != hosting.LOCAL


async def _held(beat: dict[str, Any]) -> set[str]:
    """The providers a server can be created on: their token is the app's
    (``app.core.secrets``) or the agent's (its heartbeat)."""
    return set(beat.get("providers") or ()) | await deploy_agent.tokens_here()


def _secrets_page() -> str | None:
    """Where a token can be set from here: the Secrets page, with the
    secrets component to keep it; None where only ``.env`` can."""
    return overseer_secrets.url() if overseer_secrets.has_component() else None


def _server_name() -> str | None:
    """The provisioned server's name, while what it made may still exist."""
    record = hosting.deploy_config().get("provision") or {}
    return record.get("server_name") if record.get("status") in LIVE else None


async def context() -> dict[str, Any]:
    """The card: why nothing can be asked from here, or what can."""
    if _deployed():
        return {"state": "deployed", "command": CD_COMMAND}
    if not deploy_agent.has_redis():
        return {"state": "no-redis"}
    try:
        beat = await deploy_agent.agent()
    except Exception as exc:  # noqa: BLE001 - shown in the card, logged here
        logger.warning("Deploy agent heartbeat unreadable", error=str(exc))
        return {"state": "unreachable", "error": str(exc)}
    if beat is None:
        return {"state": "no-agent", "command": AGENT_COMMAND}
    config = hosting.deploy_config()
    ready = (config.get("provision") or {}).get("status") == "ready"
    held = await _held(beat)
    open_to = [] if ready else hosting.PROVISIONABLE
    return {
        "state": "ready",
        "agent": beat,
        "partials": PARTIALS,
        "events": EVENTS,
        "event": EVENT,
        "providers": [
            {"key": p.key, "name": p.name, "size": p.size, "region": p.region}
            for p in open_to
            if p.key in held
        ],
        "missing": [
            {"key": p.key, "name": p.name, "token": p.token}
            for p in open_to
            if p.key not in held
        ],
        "secrets_page": _secrets_page(),
        "server": bool(config.get("server")),
        "destroy": _server_name(),
        "job": await job_context(),
    }


async def job_context(job_id: str | None = None) -> dict[str, Any] | None:
    """A deploy job as the card shows it (the newest by default): its
    progress, the output's tail, a price to confirm, or, for a provision
    that failed part way, the destroy that cleans up after it."""
    found = await deploy_agent.job(job_id)
    if found is None:
        return None
    action = found.name.removeprefix(deploy_agent.JOB_PREFIX)
    result = found.result or {}
    failed_provision = action == "provision" and found.status == "failed"
    names = {p.key: p.name for p in hosting.PROVIDERS}
    return {
        "id": found.job_id,
        "action": action,
        "title": TITLES.get(action, action),
        "status": found.status,
        "label": found.label,
        "error": found.error,
        "lines": result.get("lines") or [],
        "quote": result | {"name": names.get(result.get("provider"), "")}
        if action == "quote" and found.status == "done"
        else None,
        "destroy": _server_name() if failed_provision else None,
        "partials": PARTIALS,
    }


async def render_job(job_id: str | None = None) -> str:
    return fragment(JOB, job=await job_context(job_id))


def events(max_frames: int | None = None) -> AsyncIterator[str]:
    """The newest deploy job over SSE, sent again only when it changes."""
    return fragment_events(EVENT, render_job, INTERVAL_SECONDS, max_frames)


async def _confirmed(form: dict[str, str]) -> dict[str, str]:
    """A provision at the price the agent quoted, once that price is typed:
    the quote's arguments, never the form's."""
    quote = await deploy_agent.job(form["quote"]) if form.get("quote") else None
    if quote is None or quote.name != f"{deploy_agent.JOB_PREFIX}quote":
        raise RefusedError("Get a price first.")
    priced = quote.result or {}
    if quote.status != "done" or not priced.get("price"):
        raise RefusedError("Get a price first.")
    if form.get("typed", "").strip() != priced["price"]:
        raise RefusedError(f"Type the price, {priced['price']}, to create the server.")
    spec = PROTOCOL["actions"]["provision"]
    keys = (*spec["required"], *spec.get("optional", ()))
    return validate("provision", {k: priced.get(k, "") for k in keys})


async def request_args(action: str, form: dict[str, str]) -> dict[str, str]:
    """What to ask the agent for ``action``, from its form, checked as far
    as the app can (the agent checks again); refused with the reason."""
    if _deployed():
        raise RefusedError(DEPLOYED)
    beat = await deploy_agent.agent()
    if beat is None:
        raise RefusedError(f"No deploy agent is listening: start {AGENT_COMMAND}.")
    if action == "provision":
        return await _confirmed(form)
    args = validate(action, form)
    if action == "quote" and args["provider"] not in await _held(beat):
        raise RefusedError(
            f"No token to create a server on {args['provider']}: set it in "
            "Overseer > Secrets (or .env), or where the deploy agent runs."
        )
    if action == "destroy" and args["confirm"] != _server_name():
        raise RefusedError("Type the server's name exactly to destroy it.")
    return args
