"""Overseer > Deployments' actions: a new server, then deploy, back up,
list backups, roll back and destroy.

Each is asked of ``aegis deploy-agent`` on the developer's machine through
the project's Redis (``app.components.deploy.agent``), so the SSH key
never enters the app, and comes back as its job, whose output the card
streams. The form a new server is asked from is ``overseer_deploy_form``.
Offered on the dev build only: a deployed server is redeployed from the
dev Overseer or CI. The htmx Overseer only; the Flet dashboard shows the
commands.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import (
    PROTOCOL,
    RefusedError,
)
from app.core.log import logger
from app.services.system import hosting

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
# The jobs that create a server: the ones with a provision's steps.
CREATING = {a for a, spec in PROTOCOL["actions"].items() if "steps" in spec}
# The actions asked from the card, each its job; the protocol's ``kept``
# ones are fetched in the background, never asked.
TITLES = {
    "provision": "New server",
    "resume": "Resume the server",
    "deploy": "Deploy",
    "backup": "Back up",
    "backups": "Backups",
    "rollback": "Roll back",
    "destroy": "Destroy",
}


def server_name(statuses: tuple[str, ...] = LIVE) -> str | None:
    """The provisioned server's name while its record is in ``statuses``
    (by default, while what it made may still exist)."""
    record = hosting.provision_record()
    return record.get("server_name") if record.get("status") in statuses else None


def stopped() -> str | None:
    """The server a provision stopped part way through making (what it made
    still billed), to resume or destroy; None when none did."""
    return server_name(("provisioning",))


def creating(job: dict[str, Any] | None) -> bool:
    """Whether a server is being made: its job (the newest, ``job``) runs,
    or one stopped part way. The page then shows only that."""
    running = (
        job is not None and job["action"] in CREATING and job["status"] == "running"
    )
    return running or stopped() is not None


async def _agent() -> dict[str, Any]:
    """Whether the deploy agent is listening (``beat``, its heartbeat), or
    why it cannot be: no Redis to carry the asking, Redis not answering,
    nobody listening, or one older than this app."""
    if not deploy_agent.has_redis():
        return {"state": "no-redis"}
    try:
        beat = await deploy_agent.agent()
    except RefusedError as exc:  # Redis not answering: shown in the card
        logger.warning("Deploy agent heartbeat unreadable", error=str(exc))
        return {"state": "unreachable", "error": str(exc)}
    if beat is None:
        return {"state": "no-agent", "command": AGENT_COMMAND}
    if deploy_agent.stale(beat):
        return {"state": "stale", "error": deploy_agent.STALE}
    return {"state": "ready", "beat": beat}


# Where nothing is asked from here: a deployed server.
DEPLOYED_VIEW = {"view": "deployed", "command": CD_COMMAND}


async def shared() -> dict[str, Any]:
    """What both pages show of the agent: whether it can be asked (and why
    not), and its newest job, streamed."""
    agent = await _agent()
    listening = agent["state"] == "ready"
    return {
        "agent": agent,
        "partials": PARTIALS,
        "events": EVENTS,
        "event": EVENT,
        "job": await job_context() if listening else None,
    }


async def job_context(job_id: str | None = None) -> dict[str, Any] | None:
    """A deploy job as the card shows it (the newest by default): its
    progress and the output's tail, or, once one failed with a provision
    stopped part way (its own, or a destroy of it), resuming it or the
    destroy that cleans up after it; with no job left (kept a few hours),
    that provision as one that stopped. None for one the card does not ask
    (a background fetch, or an action the protocol has dropped)."""
    found = await deploy_agent.job(job_id)
    if found is None:
        name = stopped() if job_id is None else None
        if name is None:
            return None
        why = hosting.provision_record().get("error") or "It stopped part way."
        return _card("provision", "failed", error=why, stopped=name)
    action = found.name.removeprefix(deploy_agent.JOB_PREFIX)
    if not asked_from_card(action):
        return None
    return _card(
        action,
        found.status,
        found.result or {},
        label=found.label,
        error=found.error,
        stopped=stopped() if found.status == "failed" else None,
    )


def _card(
    action: str,
    status: str,
    result: dict[str, Any] | None = None,
    *,
    label: str = "",
    error: str | None = None,
    stopped: str | None = None,
) -> dict[str, Any]:
    """A job as the card shows it, from what it left (``result``)."""
    result = result or {}
    titles = PROTOCOL["actions"][action].get("steps") or {}
    return {
        "action": action,
        "title": TITLES[action],
        "status": status,
        "label": label,
        "error": error,
        "lines": result.get("lines") or [],
        "steps": _steps(result.get("progress") or {}, status, titles),
        "stopped": stopped,
        "partials": PARTIALS,
    }


def _steps(
    progress: dict[str, Any], status: str, titles: dict[str, str]
) -> list[dict[str, str]]:
    """The step bar (``progress``, where the command's steps stand, each
    named in ``titles``): each done, the one it is on current (failed, if
    the job did), the rest to come. Empty for a job that marks no steps."""
    plan, at = progress.get("steps") or [], progress.get("at")
    if at not in plan:
        return []
    here = plan.index(at)
    now = {"running": "current", "failed": "failed"}.get(status, "done")
    return [
        {
            "key": key,
            "title": titles.get(key, key),
            "status": "done" if n < here else now if n == here else "todo",
        }
        for n, key in enumerate(plan)
    ]


async def render_job(job_id: str | None = None) -> str:
    return fragment(JOB, job=await job_context(job_id))


def events(max_frames: int | None = None) -> AsyncIterator[str]:
    """The newest deploy job over SSE, sent again only when it changes."""
    return fragment_events(EVENT, render_job, INTERVAL_SECONDS, max_frames)


def asked_from_card(action: str) -> bool:
    """An action the card's buttons ask (each its job, titled): ``TITLES``,
    the protocol's actions that are not ``kept``."""
    return action in TITLES
