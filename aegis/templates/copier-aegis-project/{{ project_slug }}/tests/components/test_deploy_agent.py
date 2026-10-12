"""The app's half of the deploy agent's queue (``aegis deploy-agent``): what
it asks for, refuses to ask for, and reads back."""

import asyncio
import json

import pytest

from app.components.deploy import agent
from app.components.deploy.protocol import RefusedError
from app.services.system.job_store import RedisJobStore
from tests._fake_redis import FakeRedis

BACKUP = {"backup": "2026-10-01_020000"}


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(agent, "_client", lambda: fake)
    return fake


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
        ("quote", {"provider": "digitalocean", "size": "--yes", "region": "nyc3"}),
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


def test_only_a_deploy_job_is_shown(redis: FakeRedis) -> None:
    asyncio.run(RedisJobStore(redis).create("j1", "documents-extract:5", "Reading"))
    redis.strings[agent.LAST] = "j1"
    assert asyncio.run(agent.job()) is None


def test_its_keys_are_on_the_redis_map() -> None:
    from app.services.system.redis_keys import OWNERS

    assert agent.__name__ in OWNERS
