"""Overseer > Deployments' actions: each asked of ``aegis deploy-agent`` on
the developer's machine through the project's Redis, audited, and streamed
back as its job (``overseer_deploy_actions``)."""

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.deploy import agent
from app.components.web_frontend import overseer_deploy_actions as actions
from app.components.web_frontend import overseer_secrets
from app.core.config import settings
from app.services.system import hosting
from app.services.system.job_store import RedisJobStore
from tests._audit import recording
from tests._fake_redis import FakeRedis
from tests._secret_settings import FakeStore, use_store
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests.web.dom import none, one, select, text, triggers
from tests.web.overseer import page_html, sent_events, sign_in, status_with

PAGE = "/overseer/deployments"
CARD = "#card-deploy-from-here"
BOX = {"host": "203.0.113.7", "user": "root", "path": "/opt/my-app"}
READY = {"provider": "digitalocean", "server_name": "my-app", "status": "ready"}
QUOTE = {
    "provider": "digitalocean",
    "size": "s-1vcpu-2gb",
    "region": "nyc3",
    "price": "12.00",
    "currency": "USD",
}
TOKEN = "dop_v1_from-the-app-wxyz"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """No provider token in ``.env``, and a secrets store to set one in."""
    for p in hosting.PROVISIONABLE:
        monkeypatch.setitem(settings.__dict__, p.token, None)
    return use_store(monkeypatch)


@pytest.fixture
def redis(app: FastAPI, monkeypatch: pytest.MonkeyPatch, store: FakeStore) -> FakeRedis:
    """The dev build, Redis present, an agent listening with a DigitalOcean
    token, the app holding none, and no deploy record yet."""
    sign_in(app, monkeypatch, status_with())
    monkeypatch.setattr(settings, "BUILD_ID", hosting.LOCAL)
    monkeypatch.setattr(agent, "has_redis", lambda: True)
    fake = FakeRedis()
    monkeypatch.setattr(agent, "_client", lambda: fake)
    beat = {"host": "laptop", "version": "0.16.0", "providers": ["digitalocean"]}
    fake.strings[agent.HEARTBEAT] = json.dumps(beat)
    deployed(monkeypatch, {})
    return fake


def _agent_holds(redis: FakeRedis, *providers: str) -> None:
    beat = json.loads(redis.strings[agent.HEARTBEAT])
    redis.strings[agent.HEARTBEAT] = json.dumps(beat | {"providers": providers})


def deployed(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    """The project's ``.aegis/deploy.yml``, and this machine, off any cloud."""

    async def local() -> dict[str, Any]:
        return {
            "key": None,
            "name": "Local",
            "logo": None,
            "facts": [],
            "console": None,
        }

    monkeypatch.setattr(hosting, "deploy_config", lambda *_: config)
    monkeypatch.setattr(hosting, "running_on", local)
    use_runtime(monkeypatch, FakeRuntime(SERVER))


def _card(client: TestClient) -> Any:
    return one(page_html(client, PAGE), CARD)


def _job(redis: FakeRedis, action: str, result: dict[str, Any], error: str = "") -> str:
    """A finished deploy job, the newest."""
    store = RedisJobStore(redis)
    job_id = f"{action}0000000000000000000000000000"[:32]
    asyncio.run(store.create(job_id, f"deploy:{action}", "Waiting"))
    if error:
        asyncio.run(store.fail(job_id, error))
        redis.hashes[f"jobs:{job_id}"]["result"] = json.dumps(result)
    else:
        asyncio.run(store.finish(job_id, result))
    redis.strings[agent.LAST] = job_id
    return job_id


def _queued(redis: FakeRedis) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in redis.lists.get(agent.REQUESTS, [])]


def test_a_deployed_server_points_at_the_dev_overseer_or_ci(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with())
    deployed(monkeypatch, {})
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    card = _card(TestClient(app))
    assert "aegis deploy-cd-setup" in text(one(card, '[data-deploy-state="deployed"]'))
    none(card, "[data-write]")


def test_without_redis_it_says_the_actions_need_it(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "has_redis", lambda: False)
    card = _card(TestClient(app))
    assert "aegis add redis" in text(one(card, '[data-deploy-state="no-redis"]'))
    none(card, "[data-write]")


def test_without_an_agent_it_shows_how_to_start_one(
    redis: FakeRedis, app: FastAPI
) -> None:
    del redis.strings[agent.HEARTBEAT]
    card = _card(TestClient(app))
    said = text(one(card, '[data-deploy-state="no-agent"]'))
    assert "make serve" in said and "aegis deploy-agent" in said
    assert "SSH key, which stays on your machine" in said
    none(card, "[data-write]")


def test_a_new_server_on_each_provider_the_agent_has_a_token_for(
    redis: FakeRedis, app: FastAPI
) -> None:
    card = _card(TestClient(app))
    (form,) = select(card, "form[data-provision]")
    assert form.get("data-provision") == "digitalocean"
    assert form.get("data-write") is not None
    values = {i.get("name"): i.get("value") for i in select(form, "input")}
    assert (values["size"], values["region"]) == ("s-1vcpu-2gb", "nyc3")
    none(card, '[data-ask="deploy"]')  # nothing to redeploy yet


def test_a_deployed_project_gets_its_lifecycle_actions(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    card = _card(TestClient(app))
    for verb in ("deploy", "backup", "backups", "rollback", "destroy"):
        assert one(card, f'[data-ask="{verb}"]').get("data-write") is not None
    none(card, "form[data-provision]")  # it has its server


def test_get_price_asks_the_agent_and_is_audited(
    redis: FakeRedis, app: FastAPI
) -> None:
    client = TestClient(app)
    audit = recording(client)
    form = {"provider": "digitalocean", "size": "s-1vcpu-2gb", "region": "nyc3"}
    response = client.post(f"{actions.PARTIALS}/quote", data=form | {"domain": ""})
    assert response.status_code == 200
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == ("quote", form)
    panel = one(response.text, '[data-deploy-job="quote"]')
    assert agent.WAITING in text(panel)
    (event,) = audit.events
    assert (event["event_type"], event["outcome"]) == ("deploy.quote", "requested")
    assert event["job"] == request["job_id"]


def test_a_provider_is_offered_when_only_the_app_has_its_token(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    _agent_holds(redis)
    store.values["HCLOUD_TOKEN"] = "hetzner-token-from-the-app"
    card = _card(TestClient(app))
    (form,) = select(card, "form[data-provision]")
    assert form.get("data-provision") == "hetzner"
    none(card, '[data-token-missing="hetzner"]')


def test_with_no_token_anywhere_it_says_where_to_set_it(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    _agent_holds(redis)
    card = _card(TestClient(app))
    none(card, "form[data-provision]")
    for p in hosting.PROVISIONABLE:
        missing = one(card, f'[data-token-missing="{p.key}"]')
        assert p.token in text(missing)
        if overseer_secrets.has_component():
            assert "Overseer > Secrets" in text(missing)
            assert one(missing, "a").get("href") == overseer_secrets.url()
        else:
            assert ".env" in text(missing)
            none(missing, "a")


def test_get_price_sends_the_apps_token_outside_the_args_and_audit(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    client = TestClient(app)
    audit = recording(client)
    form = {"provider": "digitalocean", "size": "s-1vcpu-2gb", "region": "nyc3"}
    client.post(f"{actions.PARTIALS}/quote", data=form)
    (request,) = _queued(redis)
    assert request["token"] == TOKEN and request["args"] == form
    assert TOKEN not in json.dumps(audit.events, default=str)
    assert TOKEN not in json.dumps(redis.hashes)


def test_a_provider_without_a_token_here_is_refused(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    client = TestClient(app)
    audit = recording(client)
    form = {"provider": "hetzner", "size": "cx23", "region": "nbg1"}
    response = client.post(f"{actions.PARTIALS}/quote", data=form)
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)
    assert audit.events[0]["outcome"] == "refused"


def test_the_price_is_shown_and_must_be_typed_to_provision(
    redis: FakeRedis, app: FastAPI
) -> None:
    quote_id = _job(redis, "quote", QUOTE)
    client = TestClient(app)
    panel = one(page_html(client, PAGE), '[data-deploy-job="quote"]')
    assert "USD 12.00" in text(one(panel, "[data-price]"))
    form = one(panel, "form[data-confirm-price]")
    assert form.get("data-write") is not None
    url = f"{actions.PARTIALS}/provision"
    response = client.post(url, data={"quote": quote_id, "typed": "12"})
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)
    client.post(url, data={"quote": quote_id, "typed": "12.00"})
    (request,) = _queued(redis)
    assert request["action"] == "provision"
    assert request["args"] == {
        k: QUOTE[k] for k in ("provider", "size", "region", "price")
    }


def test_destroy_needs_the_server_name_typed(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    client = TestClient(app)
    url = f"{actions.PARTIALS}/destroy"
    response = client.post(url, data={"confirm": "other-app"})
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)
    client.post(url, data={"confirm": "my-app"})
    (request,) = _queued(redis)
    assert request["args"] == {"confirm": "my-app"}


def test_a_failed_provision_offers_to_destroy_what_it_made(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = READY | {"status": "provisioning"}
    deployed(monkeypatch, {"provision": started})
    lines = {"lines": ["Created server 77", "SSH on 203.0.113.7 did not come up"]}
    _job(redis, "provision", lines, error="aegis deploy-provision failed (exit 1)")
    panel = one(page_html(TestClient(app), PAGE), '[data-deploy-job="provision"]')
    assert "SSH on 203.0.113.7" in text(one(panel, "[data-lines]"))
    destroy = one(panel, '[data-ask="destroy"]')
    assert destroy.get("data-write") is not None


def test_the_newest_job_streams(redis: FakeRedis) -> None:
    _job(redis, "backup", {"lines": ["Backup complete"]})
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    assert frame.startswith(f"event: {actions.EVENT}")
    assert "Backup complete" in frame
