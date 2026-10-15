"""The app's half of the deploy agent's queue (``aegis deploy-agent``): what
it asks for, refuses to ask for, and reads back."""

import asyncio
import json
from typing import Any

import pytest

from app.components.deploy import agent
from app.components.deploy.protocol import RefusedError, kept_key
from app.core import secrets
from app.core.config import settings
from app.services.system import hosting
from app.services.system.job_store import RedisJobStore
from tests._fake_redis import FakeRedis
from tests._probe import answering
from tests._secret_settings import FakeStore, use_store

BACKUP = {"backup": "2026-10-01_020000"}
CATALOG = {"provider": "digitalocean"}
TOKEN = "dop_v1_from-the-app-wxyz"


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """The stack's Redis, faked: there in any stack, with or without one."""
    fake = FakeRedis()
    monkeypatch.setattr(agent, "has_redis", lambda: True)
    monkeypatch.setattr(agent, "_client", lambda: fake)
    return fake


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """No provider token in ``.env``, and a secrets store to set one in."""
    for p in hosting.PROVISIONABLE:
        monkeypatch.setitem(settings.__dict__, p.token, None)
    monkeypatch.setattr(hosting, "deploy_config", lambda *_: {})
    return use_store(monkeypatch)


def _sent(redis: FakeRedis) -> dict[str, Any]:
    (raw,) = redis.lists[agent.REQUESTS]
    return json.loads(raw)


def test_a_request_is_queued_with_its_job_waiting(redis: FakeRedis) -> None:
    job_id = asyncio.run(agent.enqueue("rollback", BACKUP | {"unused": ""}, "ada"))
    (raw,) = redis.lists[agent.REQUESTS]
    request = json.loads(raw)
    assert (request["job_id"], request["action"], request["by"]) == (
        job_id,
        "rollback",
        "ada",
    )
    assert request["args"] == BACKUP and request["at"]
    job = asyncio.run(agent.job())
    assert job is not None and job.job_id == job_id
    assert (job.status, job.label) == ("running", agent.WAITING)


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("shell", {}),
        ("rollback", {"backup": "$(reboot)"}),
        ("deploy", {"rolling": "yes"}),
        ("destroy", {}),
        ("catalog", {"provider": "--yes"}),
    ],
)
def test_what_the_agent_would_refuse_is_never_queued(
    redis: FakeRedis, action: str, args: dict[str, str]
) -> None:
    with pytest.raises(RefusedError):
        asyncio.run(agent.enqueue(action, args, "ada"))
    assert not redis.lists


def test_the_agent_listens_while_its_heartbeat_is_there(redis: FakeRedis) -> None:
    assert asyncio.run(agent.agent()) is None
    redis.strings[agent.HEARTBEAT] = json.dumps({"providers": ["digitalocean"]})
    beat = asyncio.run(agent.agent())
    assert beat is not None and beat["providers"] == ["digitalocean"]


def test_a_catalog_fetch_leaves_the_newest_job_alone(redis: FakeRedis) -> None:
    """Asked for in the background, so the panel keeps showing the deploy
    (or provision) it was showing."""
    shown = asyncio.run(agent.enqueue("rollback", BACKUP, "ada"))
    asyncio.run(agent.enqueue("catalog", CATALOG, "ada"))
    assert redis.strings[agent.LAST] == shown


def test_what_the_agent_keeps_is_read_back_while_it_lasts(redis: FakeRedis) -> None:
    assert asyncio.run(agent.kept("catalog", CATALOG)) is None
    sold = {"currency": "USD", "sizes": [], "regions": []}
    redis.strings[kept_key("catalog", CATALOG)] = json.dumps(sold)
    assert asyncio.run(agent.kept("catalog", CATALOG)) == sold


def test_only_a_deploy_job_is_shown(redis: FakeRedis) -> None:
    asyncio.run(RedisJobStore(redis).create("j1", "documents-extract:5", "Reading"))
    redis.strings[agent.LAST] = "j1"
    assert asyncio.run(agent.job()) is None


def test_its_keys_are_on_the_redis_map() -> None:
    from app.services.system.redis_keys import OWNERS

    assert agent.__name__ in OWNERS


def test_each_providers_token_is_a_secret_like_any_other() -> None:
    """Declared from the provider table (a cloud's, and a DNS provider's
    with one token: Porkbun's pair is ``porkbun_keys``), read from ``.env``
    (a setting) or the secrets store, and listed on Overseer > Secrets."""
    tokens = {p.token for p in hosting.PROVIDERS if p.token}
    assert {"DIGITALOCEAN_TOKEN", "HCLOUD_TOKEN", "CLOUDFLARE_API_TOKEN"} <= tokens
    assert {s.name for s in agent.SECRETS} == tokens
    assert tokens <= set(type(settings).model_fields)
    assert agent.__name__ in secrets.OWNERS


async def test_a_token_is_checked_with_its_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for entry in agent.SECRETS:
        assert entry.verify is not None and not entry.is_needed()
        sent = answering(monkeypatch, 200)
        await entry.verify(TOKEN)
        assert sent[0].method == "GET"
        assert sent[0].headers["authorization"] == f"Bearer {TOKEN}"
        answering(monkeypatch, 401)
        with pytest.raises(secrets.SecretRejectedError):
            await entry.verify(TOKEN)


def test_a_catalog_carries_the_apps_token_beside_its_args(
    redis: FakeRedis, store: FakeStore
) -> None:
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    asyncio.run(agent.enqueue("catalog", CATALOG, "ada"))
    request = _sent(redis)
    assert request["token"] == TOKEN and request["args"] == CATALOG
    assert TOKEN not in json.dumps(redis.hashes)  # the job never holds it


def test_a_destroy_carries_the_provisioned_servers_token(
    redis: FakeRedis, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    record = {"provision": {"provider": "digitalocean", "server_name": "my-app"}}
    monkeypatch.setattr(hosting, "deploy_config", lambda *_: record)
    asyncio.run(agent.enqueue("destroy", {"confirm": "my-app"}, "ada"))
    assert _sent(redis)["token"] == TOKEN


@pytest.mark.parametrize(
    ("action", "args", "held"),
    [
        ("deploy", {}, TOKEN),  # needs no token
        ("rollback", BACKUP, TOKEN),
        ("catalog", CATALOG, None),  # the app has none: the agent's own, if any
    ],
)
def test_no_token_is_sent_where_none_is_needed_or_held(
    redis: FakeRedis, store: FakeStore, action: str, args: dict[str, str], held: Any
) -> None:
    if held:
        store.values["DIGITALOCEAN_TOKEN"] = held
    asyncio.run(agent.enqueue(action, args, "ada"))
    assert "token" not in _sent(redis)


def test_a_malformed_token_is_refused_before_it_is_sent(
    redis: FakeRedis, store: FakeStore
) -> None:
    store.values["DIGITALOCEAN_TOKEN"] = "pasted with a space"
    with pytest.raises(RefusedError) as refused:
        asyncio.run(agent.enqueue("catalog", CATALOG, "ada"))
    assert "pasted" not in str(refused.value)
    assert not redis.lists


def test_a_queued_request_is_never_peeked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provision's request carries the provider token until the agent
    takes it, so Overseer > Redis names the list but never reads it."""
    from app.services.system import redis_keys

    def no_client(db: int = 0) -> Any:
        raise AssertionError("the requests list was read")

    monkeypatch.setattr(redis_keys, "redis_client", no_client)
    index = next(
        i for i, f in enumerate(redis_keys.families()) if f.pattern == agent.REQUESTS
    )
    peeked = asyncio.run(redis_keys.peek(index))
    assert peeked is not None and peeked["rows"] == []
