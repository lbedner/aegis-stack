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
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests._secret_settings import FakeStore, use_store
from tests.web.dom import none, one, select, text, triggers
from tests.web.overseer import page_html, sent_events, sign_in, status_with

PAGE = "/overseer/deployments"
CARD = "#card-deploy"
BOX = {"host": "203.0.113.7", "user": "root", "path": "/opt/my-app"}
READY = {"provider": "digitalocean", "server_name": "my-app", "status": "ready"}
TOKEN = "dop_v1_from-the-app-wxyz"
CATALOG_URL = f"{actions.PARTIALS}/catalog/digitalocean"
# What DigitalOcean sells where, as the agent caches it. The provider's
# default (s-1vcpu-2gb in nyc3) is not offered: nyc3 does not have it.
SOLD = {
    "currency": "USD",
    "regions": [
        {"slug": "tor1", "name": "Toronto 1"},
        {"slug": "fra1", "name": "Frankfurt 1"},
        {"slug": "nyc3", "name": "New York 3"},
    ],
    "sizes": [
        {
            "slug": "s-2vcpu-4gb",
            "group": "Basic",
            "memory_mb": 4096,
            "vcpus": 2,
            "disk_gb": 80,
            "prices": {"fra1": "24.00", "nyc3": "24.00"},
        },
        {
            "slug": "g-2vcpu-8gb",
            "group": "General Purpose",
            "memory_mb": 8192,
            "vcpus": 2,
            "disk_gb": 25,
            "prices": {"nyc3": "63.00"},
        },
        {
            "slug": "s-1vcpu-2gb",
            "group": "Basic",
            "memory_mb": 2048,
            "vcpus": 1,
            "disk_gb": 50,
            "prices": {"fra1": "12.00", "tor1": "12.00"},
        },
        {
            "slug": "s-1vcpu-1gb",
            "group": "Basic",
            "memory_mb": 1024,
            "vcpus": 1,
            "disk_gb": 25,
            "prices": {"fra1": "6.00", "nyc3": "6.00"},
        },
    ],
}
PICKED = {"provider": "digitalocean", "size": "s-1vcpu-2gb", "region": "fra1"}
MIB = 1024**2
# What the stack takes (``aegis.core.footprint``), steward-shaped: about
# 0.7 GB in use, 2.3 GB of limits, traefik not running here.
FOOTPRINT = {
    "services": [
        {"name": "webserver", "memory": 768 * MIB, "cpus": 2.0, "used": 400 * MIB},
        {"name": "worker-system", "memory": 1024 * MIB, "cpus": 1.0, "used": 130 * MIB},
        {"name": "scheduler", "memory": 256 * MIB, "cpus": 0.5, "used": 130 * MIB},
        {"name": "redis", "memory": 128 * MIB, "cpus": 0.25, "used": 20 * MIB},
        {"name": "traefik", "memory": 128 * MIB, "cpus": 0.25, "used": None},
        {"name": "socket-proxy", "memory": 64 * MIB, "cpus": 0.1, "used": 10 * MIB},
    ],
    "volumes": [{"name": "app-data", "size": 1200 * MIB}],
    "images": 480 * MIB,
}
FIT_URL = f"{actions.PARTIALS}/fit/digitalocean"


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


def _steps(card: Any) -> list[tuple[str, str]]:
    return [
        (s.get("data-step"), s.get("data-status")) for s in select(card, "[data-step]")
    ]


def _step(card: Any, key: str) -> Any:
    return one(card, f'[data-step="{key}"]')


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


def _sold(redis: FakeRedis, catalog: dict[str, Any] = SOLD) -> None:
    redis.strings[f"{agent.CATALOG}digitalocean"] = json.dumps(catalog)


def _form(client: TestClient, **picked: str) -> Any:
    """The DigitalOcean new-server form, as the card loads it."""
    response = client.get(CATALOG_URL, params=picked)
    assert response.status_code == 200
    return one(response.text, '[data-provision="digitalocean"]')


def _measured(redis: FakeRedis, found: dict[str, Any] = FOOTPRINT) -> None:
    redis.strings[agent.FOOTPRINT] = json.dumps(found)


def _fit(client: TestClient, size: str, **asked: str) -> Any:
    response = client.get(FIT_URL, params={"size": size, **asked})
    assert response.status_code == 200
    return one(response.text, "[data-fit]")


def _row(fit: Any, key: str) -> Any:
    return one(fit, f'[data-fit-row="{key}"]')


def _tone(row: Any) -> str:
    return one(row, "[data-why]").get("data-tone")


def _options(form: Any, name: str) -> list[tuple[str, str]]:
    return [
        (o.get("value"), text(o)) for o in select(form, f"select[name={name}] option")
    ]


def _picked(form: Any, name: str) -> str:
    return one(form, f"select[name={name}] option[selected]").get("value")


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


def test_the_steps_are_read_from_what_is_true(redis: FakeRedis, app: FastAPI) -> None:
    """An agent listening and a token held: those two are done, each said
    in a line, and the server is the step at hand."""
    card = _card(TestClient(app))
    assert _steps(card) == [
        ("agent", "done"),
        ("where", "done"),
        ("server", "current"),
    ]
    assert "laptop" in text(one(_step(card, "agent"), "[data-summary]"))
    assert "DigitalOcean" in text(one(_step(card, "where"), "[data-summary]"))
    none(_step(card, "where"), "[data-step-body]")
    one(_step(card, "server"), "[data-step-body] [data-provision]")


def test_without_an_agent_the_steps_after_it_wait(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    del redis.strings[agent.HEARTBEAT]
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    card = _card(TestClient(app))
    assert _steps(card) == [
        ("agent", "current"),
        ("where", "done"),
        ("server", "todo"),
    ]
    none(card, "[data-provision]")


def test_without_a_token_the_where_step_says_how_and_offers_a_server_of_your_own(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    _agent_holds(redis)
    card = _card(TestClient(app))
    assert _steps(card)[1:] == [("where", "current"), ("server", "todo")]
    where = one(_step(card, "where"), "[data-step-body]")
    assert "aegis deploy-init --host" in text(one(where, "[data-own-server]"))
    terminal = one(where, "details[data-terminal]")
    for p in hosting.PROVIDERS:
        assert p.command in text(terminal)


def test_a_new_server_on_each_provider_the_agent_has_a_token_for(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Each loads its form from the provider's catalog (``CATALOG_URL``)."""
    card = _card(TestClient(app))
    (form,) = select(card, "[data-provision]")
    assert form.get("data-provision") == "digitalocean"
    assert form.get("data-write") is not None
    assert (form.get("hx-get"), form.get("hx-trigger")) == (CATALOG_URL, "load")
    none(card, '[data-ask="deploy"]')  # nothing to redeploy yet


def test_without_a_catalog_it_asks_the_agent_and_waits(
    redis: FakeRedis, app: FastAPI
) -> None:
    """In the background: the job panel keeps the job it was showing."""
    form = _form(TestClient(app))
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == (
        "catalog",
        {"provider": "digitalocean"},
    )
    assert agent.LAST not in redis.strings
    one(form, "[data-loading]")
    assert form.get("hx-get") == f"{CATALOG_URL}?job={request['job_id']}"
    assert "load" in form.get("hx-trigger")


def test_once_the_agent_answers_the_form_fills_in(
    redis: FakeRedis, app: FastAPI
) -> None:
    client = TestClient(app)
    _form(client)
    (request,) = _queued(redis)
    _sold(redis)
    form = _form(client, job=request["job_id"])
    none(form, "[data-loading]")
    one(form, "select[name=size]")
    assert len(_queued(redis)) == 1  # asked once


def test_a_catalog_the_provider_refused_says_why(
    redis: FakeRedis, app: FastAPI
) -> None:
    store = RedisJobStore(redis)
    asyncio.run(store.create("c" * 32, "deploy:catalog", "Waiting"))
    asyncio.run(
        store.fail("c" * 32, "GET /sizes: HTTP 401: Unable to authenticate you")
    )
    form = _form(TestClient(app), job="c" * 32)
    assert "Unable to authenticate you" in text(one(form, "[data-error]"))
    assert one(form, "[data-retry]").get("hx-get") == CATALOG_URL


def test_the_form_offers_what_the_provider_sells(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Sizes by group, cheapest first (the price is its own line); the
    provider's default size,
    in the first region by name that offers it (its default, nyc3, does
    not)."""
    _sold(redis)
    form = _form(TestClient(app))
    groups = [g.get("label") for g in select(form, "select[name=size] optgroup")]
    assert groups == ["Basic", "General Purpose"]
    assert _options(form, "size")[:3] == [
        ("s-1vcpu-1gb", "1 GB · 1 vCPU · 25 GB"),
        ("s-1vcpu-2gb", "2 GB · 1 vCPU · 50 GB"),
        ("s-2vcpu-4gb", "4 GB · 2 vCPU · 80 GB"),
    ]
    assert _picked(form, "size") == "s-1vcpu-2gb"
    assert _options(form, "region") == [
        ("fra1", "Frankfurt 1 (fra1)"),
        ("tor1", "Toronto 1 (tor1)"),
    ]
    assert _picked(form, "region") == "fra1"
    assert "USD 12.00 a month" in text(one(form, "[data-price]"))
    assert form.get("data-write") is not None


def test_a_size_reloads_the_form_with_the_regions_that_offer_it(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    form = _form(TestClient(app), size="s-1vcpu-1gb", region="tor1")
    assert "change" in form.get("hx-trigger") and form.get("hx-get") == CATALOG_URL
    assert [slug for slug, _ in _options(form, "region")] == ["fra1", "nyc3"]
    assert _picked(form, "region") == "nyc3"  # not tor1: the default offers it
    assert "USD 6.00 a month" in text(one(form, "[data-price]"))


def test_a_provider_selling_nothing_says_so(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis, SOLD | {"sizes": []})
    form = _form(TestClient(app))
    assert "DigitalOcean offers no server" in text(one(form, "[data-error]"))


def test_the_form_loads_whether_its_size_fits(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis)
    fit = one(_form(TestClient(app)), "[data-fit]")
    assert fit.get("hx-get") == f"{FIT_URL}?size=s-1vcpu-2gb"
    assert fit.get("hx-trigger") == "load"


def test_without_a_footprint_the_agent_measures_the_stack(
    redis: FakeRedis, app: FastAPI
) -> None:
    """In the background, like the catalog; the fit waits on it."""
    _sold(redis)
    fit = _fit(TestClient(app), "s-1vcpu-2gb")
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == ("footprint", {})
    assert agent.LAST not in redis.strings
    one(fit, "[data-measuring]")
    assert fit.get("hx-get") == f"{FIT_URL}?size=s-1vcpu-2gb&job={request['job_id']}"


def test_a_2_gb_server_fits_today_but_not_at_the_limits(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Amber, saying which limits push it over. CPU limits past its cores
    are said, not counted: busy services share them, nothing runs out."""
    _sold(redis)
    _measured(redis)
    fit = _fit(TestClient(app), "s-1vcpu-2gb")
    memory = _row(fit, "memory")
    assert _tone(memory) == "warn"
    why = text(one(memory, "[data-why]"))
    assert "worker-system" in why and "webserver" in why
    assert _tone(_row(fit, "cpu")) == "muted"
    assert _tone(_row(fit, "disk")) == "ok"
    assert one(fit, "[data-verdict]").get("data-tone") == "warn"


def test_a_4_gb_server_has_room(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis)
    _measured(redis)
    fit = _fit(TestClient(app), "s-2vcpu-4gb")
    assert _tone(_row(fit, "memory")) == "ok"
    assert one(fit, "[data-verdict]").get("data-tone") == "ok"


def test_a_server_too_small_for_what_runs_today_is_red(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    _measured(redis)
    fit = _fit(TestClient(app), "s-1vcpu-1gb")
    memory = _row(fit, "memory")
    assert _tone(memory) == "error"
    assert "now" in text(one(memory, "[data-why]"))
    assert one(fit, "[data-verdict]").get("data-tone") == "error"


def test_without_the_default_size_the_cheapest_with_2_gb_is_offered(
    redis: FakeRedis, app: FastAPI
) -> None:
    sizes = [s for s in SOLD["sizes"] if s["slug"] != "s-1vcpu-2gb"]
    _sold(redis, SOLD | {"sizes": sizes})
    assert _picked(_form(TestClient(app)), "size") == "s-2vcpu-4gb"


def test_a_project_with_a_server_shows_it_and_its_actions(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No steps once there is a server: the server, what can be done to
    it, and destroying it apart."""
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    monkeypatch.setattr(
        hosting,
        "deploys_to",
        lambda *_: {
            "name": "DigitalOcean",
            "logo": None,
            "facts": [("IP", "203.0.113.7")],
            "console": None,
            "key": "digitalocean",
        },
    )
    html = page_html(TestClient(app), PAGE)
    card = one(html, CARD)
    assert "Your server" in text(one(card, "h2"))
    assert "203.0.113.7" in text(card)
    none(card, "[data-step]")
    for verb in ("deploy", "backup", "backups", "rollback"):
        assert one(card, f'[data-ask="{verb}"]').get("data-write") is not None
    none(card, "[data-provision]")  # it has its server
    destroy = one(one(html, "#card-destroy"), '[data-ask="destroy"]')
    assert destroy.get("data-write") is not None


def test_a_job_for_an_action_gone_from_the_page_is_not_shown(
    redis: FakeRedis, app: FastAPI
) -> None:
    """The quote step went; a quote job still in Redis is not news."""
    _job(redis, "quote", {"lines": []}, error="s-1vcpu-2gb is not offered in nyc3")
    none(_card(TestClient(app)), "[data-deploy-job]")


def test_a_provider_is_offered_when_only_the_app_has_its_token(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    _agent_holds(redis)
    store.values["HCLOUD_TOKEN"] = "hetzner-token-from-the-app"
    card = _card(TestClient(app))
    (form,) = select(card, "[data-provision]")
    assert form.get("data-provision") == "hetzner"
    none(card, '[data-token-missing="hetzner"]')


def test_with_no_token_anywhere_it_says_where_to_set_it(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    _agent_holds(redis)
    card = _card(TestClient(app))
    none(card, "[data-provision]")
    for p in hosting.PROVISIONABLE:
        missing = one(card, f'[data-token-missing="{p.key}"]')
        assert p.token in text(missing)
        if overseer_secrets.has_component():
            assert "Overseer > Secrets" in text(missing)
            assert one(missing, "a").get("href") == overseer_secrets.url()
        else:
            assert ".env" in text(missing)
            none(missing, "a")


def test_provisioning_sends_the_apps_token_outside_the_args_and_audit(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    _sold(redis)
    client = TestClient(app)
    audit = recording(client)
    client.post(f"{actions.PARTIALS}/provision", data=PICKED | {"typed": "12.00"})
    (request,) = _queued(redis)
    assert request["token"] == TOKEN and request["args"] == PICKED | {"price": "12.00"}
    assert TOKEN not in json.dumps(audit.events, default=str)
    assert TOKEN not in json.dumps(redis.hashes)


def test_a_provider_without_a_token_here_is_refused(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    client = TestClient(app)
    audit = recording(client)
    form = {"provider": "hetzner", "size": "cx23", "region": "nbg1", "typed": "4.15"}
    response = client.post(f"{actions.PARTIALS}/provision", data=form)
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)
    assert audit.events[0]["outcome"] == "refused"


def test_the_price_shown_must_be_typed_to_provision(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    client = TestClient(app)
    audit = recording(client)
    url = f"{actions.PARTIALS}/provision"
    response = client.post(url, data=PICKED | {"typed": "12"})
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)
    response = client.post(url, data=PICKED | {"typed": "12.00", "domain": ""})
    (request,) = _queued(redis)
    assert request["action"] == "provision"
    assert request["args"] == PICKED | {"price": "12.00"}
    assert agent.WAITING in text(one(response.text, '[data-deploy-job="provision"]'))
    assert [e["outcome"] for e in audit.events] == ["refused", "requested"]


@pytest.mark.parametrize(
    "picked",
    [
        PICKED | {"region": "nyc3"},  # not offered there
        PICKED | {"size": "s-64vcpu-512gb"},  # not sold
    ],
)
def test_what_the_provider_does_not_sell_there_is_refused(
    redis: FakeRedis, app: FastAPI, picked: dict[str, str]
) -> None:
    _sold(redis)
    url = f"{actions.PARTIALS}/provision"
    response = TestClient(app).post(url, data=picked | {"typed": "12.00"})
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)


def test_once_the_catalog_has_expired_provisioning_says_to_reload(
    redis: FakeRedis, app: FastAPI
) -> None:
    url = f"{actions.PARTIALS}/provision"
    response = TestClient(app).post(url, data=PICKED | {"typed": "12.00"})
    assert "reload" in triggers(response)["toast"]["text"].lower()
    assert not _queued(redis)


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
