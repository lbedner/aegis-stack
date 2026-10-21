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
from functools import partial
from importlib.util import find_spec
from typing import Any

from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import (
    DRILL,
    PROTOCOL,
    PROVISION_STEPS,
    RefusedError,
)
from app.core.formatting import format_relative_time
from app.core.log import logger
from app.services.system import hosting
from app.services.system.job_store import KEEP_SECONDS
from app.services.system.jobs import JobSnapshot

from .overseer_live import fragment_events
from .rendering import fragment, status_cell, with_query

EVENTS = "/overseer/events/deployments/job"
EVENT = "deploy-job"
PARTIALS = "/partials/overseer/deployments"
JOB = "pages/overseer/deployments/_job.html"
PAGE = "/overseer/deployments"  # the Deployments page (its nav item's url)
JOBS_URL = f"{PAGE}/jobs"  # a job's own page: ?job=<id>
INTERVAL_SECONDS = 1.0
AGENT_COMMAND = "aegis deploy-agent"
CD_COMMAND = "aegis deploy-cd-setup"
LIVE = ("provisioning", "ready")  # a provision record whose resources may exist
# The jobs that create a server: the ones with a provision's steps.
CREATING = {
    a for a, spec in PROTOCOL["actions"].items() if spec.get("steps") is PROVISION_STEPS
}
# The actions asked from the card, each its job; the protocol's ``kept``
# ones are fetched in the background, never asked.
TITLES = {
    "provision": "New server",
    "resume": "Resume the server",
    "deploy": "Deploy",
    "deploy-rolling": "Deploy without downtime",
    "backup": "Back up",
    "upload-storage": "Bring missing files",
    DRILL: "Rehearse a restore",
    "rollback": "Roll back",
    "destroy": "Destroy",
}
# A restore is rehearsed on the nightly off-site copy: only a project with
# that job (deploy, a database and the scheduler) has one to rehearse.
DRILLS = find_spec("app.services.system.offsite") is not None


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


async def agent_state() -> dict[str, Any]:
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
    said = _said(beat)
    if deploy_agent.stale(beat):
        return {"state": "stale", "error": deploy_agent.STALE, "said": said}
    return {"state": "ready", "beat": beat, "said": said}


def _said(beat: dict[str, Any]) -> str:
    """Which agent listens: the checkout it runs in (each worktree or copy
    runs its own; an older agent names only its machine), its aegis and
    its pid, to stop it by."""
    where = beat.get("root") or beat.get("host")
    return f"Listening in {where} (aegis {beat.get('version')}, pid {beat.get('pid')})"


# Where nothing is asked from here: a deployed server.
DEPLOYED_VIEW = {"view": "deployed", "command": CD_COMMAND}


async def shared() -> dict[str, Any]:
    """What both pages show of the agent: whether it can be asked (and why
    not), and its newest job, streamed."""
    agent = await agent_state()
    listening = agent["state"] == "ready"
    return {
        "agent": agent,
        "partials": PARTIALS,
        "drill": {"verb": DRILL, "label": TITLES[DRILL]} if DRILLS else None,
        "events": EVENTS,
        "event": EVENT,
        "job": await job_context() if listening else None,
    }


async def job_context(
    job_id: str | None = None, *, whole: bool = False
) -> dict[str, Any] | None:
    """A deploy job as a card shows it (the newest by default), or
    ``whole``, as its own page does; once one failed with a provision
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
        return _card("provision", "failed", error=why, stopped=name, whole=whole)
    return _snapshot_card(found, whole=whole)


def _snapshot_card(found: JobSnapshot, *, whole: bool) -> dict[str, Any] | None:
    """A job the store holds (``found``) as ``job_context`` shows it."""
    action = deploy_agent.action_of(found)
    if not asked_from_card(action):
        return None
    return _card(
        action,
        found.status,
        found.result or {},
        label=found.label,
        error=found.error,
        stopped=stopped() if found.status == "failed" else None,
        job_id=found.job_id,
        whole=whole,
    )


def job_url(job_id: str) -> str:
    """A job's own page, its output whole (``JOBS_URL``)."""
    return with_query(JOBS_URL, job=job_id)


def job_events(job_id: str | None = None) -> str:
    """Where a job streams whole (``events``): ``job_id``, or the newest
    (New server's, which a resume asked there takes over)."""
    return with_query(EVENTS, job=job_id, whole="1")


def _card(
    action: str,
    status: str,
    result: dict[str, Any] | None = None,
    *,
    label: str = "",
    error: str | None = None,
    stopped: str | None = None,
    job_id: str | None = None,
    whole: bool,
) -> dict[str, Any]:
    """A job as a card shows it, from what it left (``result``): where it
    stands and a link to it; or ``whole``, its steps and output too."""
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
        "url": job_url(job_id) if job_id else None,
        "whole": whole,
    }


def _steps(
    progress: dict[str, Any], status: str, titles: dict[str, str]
) -> list[dict[str, str]]:
    """The step bar (``progress``, where the command's steps stand, each
    named in ``titles``): each done, the one it is on current (failed, if
    the job did), the rest to come. Empty for a job that marks no steps,
    or steps it does not declare (an older CLI's)."""
    plan, at = progress.get("steps") or [], progress.get("at")
    if at not in plan or not titles.keys() >= set(plan):
        return []
    here = plan.index(at)
    now = {"running": "current", "failed": "failed"}.get(status, "done")
    return [
        {
            "key": key,
            "title": titles[key],
            "status": "done" if n < here else now if n == here else "todo",
        }
        for n, key in enumerate(plan)
    ]


async def render_job(job_id: str | None = None, *, whole: bool = False) -> str:
    return fragment(JOB, job=await job_context(job_id, whole=whole))


def events(
    job_id: str | None = None, max_frames: int | None = None, *, whole: bool = False
) -> AsyncIterator[str]:
    """A deploy job over SSE, sent again only when it changes: the newest,
    as the cards show it, or ``whole`` (``job_id`` always is: Jobs)."""
    render = partial(render_job, job_id, whole=whole or job_id is not None)
    return fragment_events(EVENT, render, INTERVAL_SECONDS, max_frames)


JOB_COLUMNS = [
    {"key": "job", "label": "Job", "kind": "link", "target": "#overseer-main"},
    {"key": "status", "label": "Status", "kind": "status"},
    {"key": "started", "label": "Started"},
    {"key": "said", "label": "Last line", "wrap": True},
]
# A job (or a deploy event) as a status cell: done unless one of these.
DONE = ("Done", "ok")
STATUS_CELLS = {"running": ("Running", "accent"), "failed": ("Failed", "error")}


async def jobs_page(picked: str | None) -> dict[str, Any]:
    """The Jobs page: every deploy job still kept, newest first, each
    opening here, and the one picked (the newest unless another is)
    whole, streamed while it runs; or why the agent cannot be asked."""
    agent = await agent_state()
    if agent["state"] in ("no-redis", "unreachable"):
        return {"agent": agent, "rows": None}
    found = [
        j
        for j in await deploy_agent.jobs()
        if asked_from_card(deploy_agent.action_of(j))
    ]
    shown = next((j for j in found if j.job_id == picked), found[0] if found else None)
    running = shown is not None and shown.status == "running"
    return {
        "agent": agent,
        "job": _snapshot_card(shown, whole=True) if shown else None,
        "events": job_events(shown.job_id) if shown and running else None,
        "event": EVENT,
        "columns": JOB_COLUMNS,
        "rows": [_job_row(j) for j in found],
        "kept_hours": KEEP_SECONDS // 3600,
    }


def _job_row(job: JobSnapshot) -> dict[str, Any]:
    """A job as the Jobs table lists it."""
    return {
        "job": {
            "label": TITLES[deploy_agent.action_of(job)],
            "url": job_url(job.job_id),
        },
        "status": status_cell(*STATUS_CELLS.get(job.status, DONE)),
        "started": format_relative_time(job.started_at),
        "said": job.error or job.label,
    }


def asked_from_card(action: str) -> bool:
    """An action the card's buttons ask (each its job, titled): ``TITLES``,
    the protocol's actions that are not ``kept``."""
    return action in TITLES
