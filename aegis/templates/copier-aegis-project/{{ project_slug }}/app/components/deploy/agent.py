"""The app's half of the deploy agent's queue (``aegis deploy-agent``).

Deploying needs what the app does not have (the aegis CLI, the SSH key,
the cloud token), so the Overseer asks and the agent, on the developer's
machine, does. A request goes onto a Redis list with a job record beside
it (``RedisJobStore``); the agent runs it and writes the command's output
into that record, which the page streams like any other job. The agent
keeps a heartbeat key while it listens, naming the providers it holds
tokens for, never the tokens.

The protocol (key names, the actions, each argument's pattern, the check
a request must pass) is ``protocol.py`` beside this file, which the aegis
CLI loads out of the template it ships. Without Redis there is no queue,
and the Overseer says so.
"""

from datetime import UTC, datetime
import json
from typing import Any
import uuid

from app.components.deploy.protocol import PROTOCOL, validate
from app.core.config import settings
from app.core.key_family import KeyFamily
from app.services.system.job_store import KEEP_SECONDS, RedisJobStore
from app.services.system.jobs import JobSnapshot

REQUESTS = PROTOCOL["requests"]
HEARTBEAT = PROTOCOL["heartbeat"]
LAST = PROTOCOL["last"]
JOB_PREFIX = "deploy:"  # a job's name: ``deploy:<action>``
WAITING = "Waiting for the deploy agent"

REDIS_KEYS = (
    KeyFamily(
        HEARTBEAT,
        "string",
        "Deploy agent",
        "aegis deploy-agent on the developer's machine, refreshed while it listens",
        "Deploy agent",
    ),
    KeyFamily(
        REQUESTS,
        "list",
        "Deploy requests",
        "Overseer deploy actions waiting for the deploy agent",
        "Deploy agent",
    ),
    KeyFamily(
        LAST,
        "string",
        "Last deploy job",
        "The job of the newest deploy action, which Overseer > Deployments shows",
        "Deploy agent",
    ),
)


def has_redis() -> bool:
    """Whether this stack has the Redis the queue lives on."""
    return hasattr(settings, "REDIS_URL")


def _client() -> Any:
    from app.services.system.redis_keys import redis_client

    return redis_client()


async def enqueue(action: str, args: dict[str, str], by: str) -> str:
    """Ask the agent for ``action``: its job, waiting, then the request.
    The job's id."""
    args = validate(action, args)
    job_id = uuid.uuid4().hex
    request = {
        "job_id": job_id,
        "action": action,
        "args": args,
        "by": by,
        "at": datetime.now(UTC).isoformat(),
    }
    client = _client()
    try:
        await RedisJobStore(client).create(job_id, f"{JOB_PREFIX}{action}", WAITING)
        await client.rpush(REQUESTS, json.dumps(request))
        await client.set(LAST, job_id, ex=KEEP_SECONDS)
    finally:
        await client.aclose()
    return job_id


def _text(value: Any) -> str | None:
    return value.decode() if isinstance(value, bytes) else value


async def agent() -> dict[str, Any] | None:
    """The listening agent's heartbeat, or None when none is listening."""
    client = _client()
    try:
        beat = _text(await client.get(HEARTBEAT))
    finally:
        await client.aclose()
    return json.loads(beat) if beat else None


async def job(job_id: str | None = None) -> JobSnapshot | None:
    """A deploy job (the newest when no id is given), or None."""
    client = _client()
    try:
        job_id = job_id or _text(await client.get(LAST))
        found = await RedisJobStore(client).get(job_id) if job_id else None
    finally:
        await client.aclose()
    if found is None or not found.name.startswith(JOB_PREFIX):
        return None
    return found
