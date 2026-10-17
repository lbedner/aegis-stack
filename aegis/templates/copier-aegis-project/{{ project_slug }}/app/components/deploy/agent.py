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

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from typing import Any
import uuid

from app.components.deploy.protocol import (
    PROTOCOL,
    RefusedError,
    checked_token,
    is_kept,
    kept_key,
    record_dns_provider,
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
JOB_PREFIX = "deploy:"  # a job's name: ``deploy:<action>``
WAITING = "Waiting for the deploy agent"
STALE = (
    "The deploy agent listening is older than this app. Restart it with "
    "make serve (after uv tool upgrade aegis-stack, if the CLI is older too)."
)

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
        kept_key("catalog", {"provider": "*"}),
        "string",
        "Provider catalog",
        "A provider's sizes and regions, for the new-server form",
        "Deploy agent",
    ),
    KeyFamily(
        kept_key("account", {"provider": "*"}),
        "string",
        "Provider account",
        "What a provider account runs now and has cost this month",
        "Deploy agent",
    ),
    KeyFamily(
        kept_key("footprint", {}),
        "string",
        "Stack footprint",
        "What the production services take, measured by the agent",
        "Deploy agent",
    ),
)


def _verify(url: str) -> Callable[[str], Awaitable[None]]:
    """A token check: one authenticated GET to the provider's ``check``."""

    async def verify(token: str) -> None:
        await probe(url, headers={"Authorization": f"Bearer {token}"})

    return verify


# What this module reads (``app.core.secrets``): each provider's API token,
# a cloud's or a DNS provider's (Porkbun's pair is ``porkbun_keys``).
SECRETS = tuple(
    Secret(
        p.token,
        owner=f"DNS ({p.name})" if "DNS" in p.can else "Deploy",
        label=f"{p.name} API token",
        verify=_verify(p.check) if p.check else None,
    )
    for p in hosting.PROVIDERS
    if p.token
)


def has_redis() -> bool:
    """Whether this stack has the Redis the queue lives on."""
    return hasattr(settings, "REDIS_URL")


def _client() -> Any:
    from app.services.system.redis_keys import redis_client

    return redis_client()


def _redis_errors() -> tuple[type[Exception], ...]:
    """What Redis raises when it does not answer; nothing in a stack
    without Redis (no package to raise it)."""
    try:
        from redis.exceptions import RedisError
    except ImportError:
        return ()
    return (RedisError,)


@asynccontextmanager
async def _redis() -> AsyncIterator[Any]:
    """A client for one exchange, closed after it. Redis not answering, or
    a stack without it, is a refusal saying so, which every caller already
    shows (never a 500)."""
    if not has_redis():
        raise RefusedError("This stack has no Redis to reach the deploy agent through.")
    client = _client()
    try:
        yield client
    except _redis_errors() as exc:
        raise RefusedError(f"Redis is not answering: {exc}") from None
    finally:
        await client.aclose()


async def tokens_here() -> set[str]:
    """The providers whose token the app holds (``.env`` or the store)."""
    found = await secrets.get_many(*(entry.name for entry in SECRETS))
    return {p.key for p in hosting.PROVISIONABLE if p.token and found.get(p.token)}


async def _token(action: str, args: dict[str, str]) -> str | None:
    """The app's token for the provider ``action`` acts on, checked as the
    agent will check it; None where it needs none or the app has none."""
    record = hosting.provision_record()
    key = token_provider(action, args, record)
    found = hosting.provider(key)
    if found is None or found not in hosting.PROVISIONABLE or found.token is None:
        return None
    return checked_token(action, await secrets.get(found.token))


async def _dns_keys(action: str, args: dict[str, str]) -> dict[str, str]:
    """The DNS provider's keys ``action`` carries: the provider a provision
    on a domain names (``dns``), else the one the provisioned server's
    record was made at; nothing for an action that needs none (a provision
    with no domain), or keys the app lacks."""
    if not PROTOCOL["actions"][action].get("dns"):
        return {}
    if action == "provision" and not args.get("domain"):
        return {}
    record = hosting.provision_record()
    found = hosting.provider(args.get("dns") or record_dns_provider(record))
    if found is None or found not in hosting.DNS:
        return {}
    held = await secrets.get_many(*found.secrets)
    return {name: value for name in found.secrets if (value := held.get(name))}


async def enqueue(action: str, args: dict[str, str], by: str) -> str:
    """Ask the agent for ``action``: its job, waiting, then the request,
    with the app's provider token beside its arguments where it needs one;
    the newest job the page shows unless what it finds is ``kept``. The
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
    if dns := await _dns_keys(action, args):
        request["dns_keys"] = dns
    async with _redis() as client:
        await RedisJobStore(client).create(job_id, f"{JOB_PREFIX}{action}", WAITING)
        await client.rpush(REQUESTS, json.dumps(request))
        if not is_kept(action):
            await client.set(LAST, job_id, ex=KEEP_SECONDS)
    return job_id


def _text(value: Any) -> str | None:
    return value.decode() if isinstance(value, bytes) else value


async def agent() -> dict[str, Any] | None:
    """The listening agent's heartbeat, or None when none is listening."""
    return await _kept(HEARTBEAT)


def stale(beat: dict[str, Any]) -> bool:
    """Whether the listening agent (``beat``) is older than this app: it
    does not name an action the app asks for, or speaks an older revision
    of the protocol."""
    return beat.get("revision", 1) < PROTOCOL["revision"] or not set(
        PROTOCOL["actions"]
    ) <= set(beat.get("actions") or ())


async def _kept(key: str) -> dict[str, Any] | None:
    """What the agent left under ``key``; None once it has expired, or
    before the agent has been asked."""
    async with _redis() as client:
        found = _text(await client.get(key))
    return json.loads(found) if found else None


async def kept(action: str, args: dict[str, str]) -> dict[str, Any] | None:
    """What the agent found for a ``kept`` action (a provider's catalog or
    account, the stack's footprint) as it last looked; None once expired,
    or before it was asked."""
    return await _kept(kept_key(action, args))


async def forget(action: str, args: dict[str, str]) -> None:
    """Drop what the agent keeps for ``action``: the next read asks it
    again (a part's refresh)."""
    async with _redis() as client:
        await client.delete(kept_key(action, args))


def action_of(job: JobSnapshot) -> str:
    """The protocol action a deploy job runs (its name, ``JOB_PREFIX``)."""
    return job.name.removeprefix(JOB_PREFIX)


async def jobs() -> list[JobSnapshot]:
    """Every deploy job still kept (a few hours), newest first."""
    async with _redis() as client:
        found = await RedisJobStore(client).list_jobs()
    mine = [j for j in found if j.name.startswith(JOB_PREFIX)]
    return sorted(mine, key=lambda j: j.started_at, reverse=True)


async def job(job_id: str | None = None) -> JobSnapshot | None:
    """A deploy job (the newest when no id is given), or None."""
    async with _redis() as client:
        job_id = job_id or _text(await client.get(LAST))
        found = await RedisJobStore(client).get(job_id) if job_id else None
    if found is None or not found.name.startswith(JOB_PREFIX):
        return None
    return found
