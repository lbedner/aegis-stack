"""The app's half of the deploy agent's queue (``aegis deploy-agent``).

Deploying needs what the app does not have (the aegis CLI, the SSH key),
so the Overseer asks and the agent, on the developer's machine, does. A
request goes onto a Redis list with a job record beside it
(``RedisJobStore``); the agent runs it and writes the command's output
into that record, which the page streams like any other job. The agent
keeps a heartbeat key while it listens, naming the providers it holds
tokens for in its own environment, never the tokens.

The cloud token is a secret like any other (``SECRETS``, one per provider
aegis provisions on): a request that acts on a provider's account carries
the app's token for it, outside its audited arguments. Without one the
agent uses its own environment's.

The protocol (key names, the actions, each argument's pattern, the check
a request must pass) is ``protocol.py`` beside this file, which the aegis
CLI loads out of the template it ships. Without Redis there is no queue,
and the Overseer says so.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import json
from typing import Any
import uuid

from app.components.deploy.protocol import (
    PROTOCOL,
    checked_token,
    token_provider,
    validate,
)
from app.core import secrets
from app.core.config import settings
from app.core.key_family import KeyFamily
from app.core.secrets import Secret, probe
from app.services.system import hosting
from app.services.system.job_store import KEEP_SECONDS, RedisJobStore
from app.services.system.jobs import JobSnapshot

REQUESTS = PROTOCOL["requests"]
HEARTBEAT = PROTOCOL["heartbeat"]
LAST = PROTOCOL["last"]
CATALOG = PROTOCOL["catalog"]
FOOTPRINT = PROTOCOL["footprint"]
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
        # A provision's request carries the provider token: never peeked.
        peek=False,
    ),
    KeyFamily(
        LAST,
        "string",
        "Last deploy job",
        "The job of the newest deploy action, which Overseer > Deployments shows",
        "Deploy agent",
    ),
    KeyFamily(
        f"{CATALOG}*",
        "string",
        "Provider catalog",
        "A provider's sizes and regions, for the new-server form, kept an hour",
        "Deploy agent",
    ),
    KeyFamily(
        FOOTPRINT,
        "string",
        "Stack footprint",
        "What the production services take, measured by the agent, kept ten minutes",
        "Deploy agent",
    ),
)


def _verify(url: str) -> Callable[[str], Awaitable[None]]:
    """A token check: one authenticated GET to the provider's ``check``."""

    async def verify(token: str) -> None:
        await probe(url, headers={"Authorization": f"Bearer {token}"})

    return verify


# What this module reads (``app.core.secrets``): each provider's API token.
SECRETS = tuple(
    Secret(
        p.token,
        owner="Deploy",
        label=f"{p.name} API token",
        verify=_verify(p.check) if p.check else None,
    )
    for p in hosting.PROVISIONABLE
    if p.token
)


def has_redis() -> bool:
    """Whether this stack has the Redis the queue lives on."""
    return hasattr(settings, "REDIS_URL")


def _client() -> Any:
    from app.services.system.redis_keys import redis_client

    return redis_client()


async def tokens_here() -> set[str]:
    """The providers whose token the app holds (``.env`` or the store)."""
    found = await secrets.get_many(*(entry.name for entry in SECRETS))
    return {p.key for p in hosting.PROVISIONABLE if p.token and found.get(p.token)}


async def _token(action: str, args: dict[str, str]) -> str | None:
    """The app's token for the provider ``action`` acts on, checked as the
    agent will check it; None where it needs none or the app has none."""
    record = hosting.deploy_config().get("provision") or {}
    key = token_provider(action, args, record)
    provider = next((p for p in hosting.PROVISIONABLE if p.key == key), None)
    if provider is None or provider.token is None:
        return None
    return checked_token(action, await secrets.get(provider.token))


async def enqueue(action: str, args: dict[str, str], by: str) -> str:
    """Ask the agent for ``action``: its job, waiting, then the request,
    with the app's provider token beside its arguments where it needs one;
    the newest job the page shows unless it runs in the background. The
    job's id."""
    args = validate(action, args)
    job_id = uuid.uuid4().hex
    request = {
        "job_id": job_id,
        "action": action,
        "args": args,
        "by": by,
        "at": datetime.now(UTC).isoformat(),
    }
    if token := await _token(action, args):
        request["token"] = token
    client = _client()
    try:
        await RedisJobStore(client).create(job_id, f"{JOB_PREFIX}{action}", WAITING)
        await client.rpush(REQUESTS, json.dumps(request))
        if not PROTOCOL["actions"][action].get("background"):
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


async def _kept(key: str) -> dict[str, Any] | None:
    """What the agent left under ``key``; None once it has expired, or
    before the agent has been asked."""
    client = _client()
    try:
        found = _text(await client.get(key))
    finally:
        await client.aclose()
    return json.loads(found) if found else None


async def catalog(provider: str) -> dict[str, Any] | None:
    """What ``provider`` sells where, as the agent last fetched it."""
    return await _kept(f"{CATALOG}{provider}")


async def footprint() -> dict[str, Any] | None:
    """What the stack's production services take, as last measured."""
    return await _kept(FOOTPRINT)


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
