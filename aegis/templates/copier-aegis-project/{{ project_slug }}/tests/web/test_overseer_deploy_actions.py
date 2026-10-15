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
from app.components.deploy.protocol import PROTOCOL, PROVISION_STEPS, is_kept, kept_key
from app.components.web_frontend import overseer_deploy_actions as actions
from app.components.web_frontend import overseer_deploy_form as deploy_form
from app.components.web_frontend import overseer_secrets
from app.core import exposure, secrets
from app.core.config import settings
from app.services.system import hosting
from app.services.system.job_store import RedisJobStore
from tests._audit import recording
from tests._fake_redis import FakeRedis
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests._secret_settings import FakeStore, use_store
from tests.web.dom import chosen, none, one, select, table_rows, text, triggers
from tests.web.overseer import (
    frame_html,
    page_html,
    sent_events,
    sign_in,
    status_with,
)

PAGE = "/overseer/deployments"
NEW = f"{PAGE}/new"  # the steps to a new server
CARD = "#card-deploy"
BOX = {"host": "203.0.113.7", "user": "root", "path": "/opt/my-app"}
READY = {"provider": "digitalocean", "server_name": "my-app", "status": "ready"}
TOKEN = "dop_v1_from-the-app-wxyz"
CATALOG_URL = deploy_form.panel_path("catalog", "digitalocean")
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
FOOTPRINT: dict[str, Any] = {
    "services": [
        {"name": "webserver", "memory": 768 * MIB, "cpus": 1.0, "used": 400 * MIB},
        {"name": "worker-system", "memory": 1024 * MIB, "cpus": 1.0, "used": 130 * MIB},
        {"name": "scheduler", "memory": 256 * MIB, "cpus": 0.5, "used": 130 * MIB},
        {"name": "redis", "memory": 128 * MIB, "cpus": 0.25, "used": 20 * MIB},
        {"name": "traefik", "memory": 128 * MIB, "cpus": 0.25, "used": None},
        {"name": "socket-proxy", "memory": 64 * MIB, "cpus": 0.1, "used": 10 * MIB},
    ],
    "data": 1200 * MIB,
    "images": 480 * MIB,
}
FIT_URL = deploy_form.panel_path("fit", "digitalocean")
# What the DigitalOcean account runs now, as the agent keeps it.
ACCOUNT = {
    "servers": [
        {
            "name": "old-box",
            "size": "s-1vcpu-1gb",
            "region": "nyc1",
            "price": "6.00",
            "created": "2025-01-05T08:00:00Z",
            "project": None,
        },
        {
            "name": "my-app",
            "size": "s-1vcpu-2gb",
            "region": "tor1",
            "price": "12.00",
            "created": "2026-09-01T10:00:00Z",
            "project": "my-app",
        },
    ],
    "month_to_date": "23.17",
    "missing": [],
    "currency": "USD",
}


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
    monkeypatch.setattr(settings, "BUILD_ID", exposure.LOCAL)
    monkeypatch.setattr(agent, "has_redis", lambda: True)
    fake = FakeRedis()
    monkeypatch.setattr(agent, "_client", lambda: fake)
    beat = {
        "host": "laptop",
        "root": "/home/ada/my-app",
        "pid": 4242,
        "version": "0.16.0",
        "providers": ["digitalocean"],
        "actions": list(PROTOCOL["actions"]),
        "revision": PROTOCOL["revision"],
    }
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


def _card(client: TestClient, page: str = NEW) -> Any:
    return one(page_html(client, page), CARD)


def _steps(card: Any) -> list[tuple[str, str]]:
    return [
        (s.get("data-step"), s.get("data-status")) for s in select(card, "[data-step]")
    ]


def _step(card: Any, key: str) -> Any:
    return one(card, f'[data-step="{key}"]')


def _job(
    redis: FakeRedis,
    action: str,
    result: dict[str, Any],
    error: str = "",
    running: bool = False,
) -> str:
    """A deploy job, the newest: finished, failed with ``error``, or still
    ``running``."""
    store = RedisJobStore(redis)
    job_id = f"{action}0000000000000000000000000000"[:32]
    asyncio.run(store.create(job_id, f"deploy:{action}", "Waiting"))
    if running:
        redis.hashes[f"jobs:{job_id}"]["result"] = json.dumps(result)
    elif error:
        asyncio.run(store.fail(job_id, error))
        redis.hashes[f"jobs:{job_id}"]["result"] = json.dumps(result)
    else:
        asyncio.run(store.finish(job_id, result))
    redis.strings[agent.LAST] = job_id
    return job_id


def _queued(redis: FakeRedis) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in redis.lists.get(agent.REQUESTS, [])]


def _keep(redis: FakeRedis, action: str, found: dict[str, Any], **args: str) -> None:
    """What the agent keeps for ``action``, as it leaves it in Redis."""
    redis.strings[kept_key(action, args)] = json.dumps(found)


def _sold(redis: FakeRedis, catalog: dict[str, Any] = SOLD) -> None:
    _keep(redis, "catalog", catalog, provider="digitalocean")


def _form(client: TestClient, **picked: str) -> Any:
    """The DigitalOcean new-server form, as the card loads it."""
    response = client.get(CATALOG_URL, params=picked)
    assert response.status_code == 200
    return one(response.text, '[data-provision="digitalocean"]')


def _measured(redis: FakeRedis, found: dict[str, Any] = FOOTPRINT) -> None:
    _keep(redis, "footprint", found)


def _accounted(redis: FakeRedis, found: dict[str, Any] = ACCOUNT) -> None:
    _keep(redis, "account", found, provider="digitalocean")


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


def test_the_overview_is_what_is_deployed_the_steps_their_own_page(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Without a server the overview says so and leads to the steps,
    which are their own page (and in the sub-menu)."""
    html = page_html(TestClient(app), PAGE)
    none(html, "[data-steps]")
    none_yet = one(one(html, CARD), '[data-deploy-state="no-server"]')
    one(none_yet, f'a[href="{NEW}"]')
    one(_card(TestClient(app)), "[data-steps]")


def test_while_a_server_is_being_made_the_overview_points_to_it(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its first deploy is one of its steps: shown on New server, not as a
    server to deploy to, back up or destroy."""
    server = {"host": "203.0.113.7", "user": "root", "path": "/opt/my-app"}
    stopped = READY | {"status": "provisioning"}
    deployed(monkeypatch, {"server": server, "provision": stopped})
    _job(redis, "provision", {"lines": ["Failed to start services"]}, error="exit 1")
    card = one(page_html(TestClient(app), PAGE), CARD)
    one(one(card, '[data-deploy-state="creating"]'), f'a[href="{NEW}"]')
    none(card, "[data-deploy-job]")
    none(card, "[data-ask]")


def test_the_overview_shows_every_server_in_each_connected_account(
    redis: FakeRedis, app: FastAPI
) -> None:
    """From what the agent last found (kept a few minutes), so opening the
    page asks the cloud nothing; nothing is being bought, so no total
    with a new one. Which account is its logo, not a sentence naming it."""
    _accounted(redis)
    account = one(page_html(TestClient(app), PAGE), "[data-account]")
    assert hosting.BY_KEY["digitalocean"].domain in one(account, "p img").get("src")
    assert "DigitalOcean: 2 servers, $18.00 a month" in text(account)
    assert "Already in" not in text(account)
    assert "With this one" not in text(account)
    assert not _queued(redis)
    rows = select(account, "tbody tr")  # dearest first, aegis's own marked
    assert [text(r).split()[0] for r in rows] == ["my-app", "old-box"]
    assert [text(r["A month"]) for r in table_rows(account)] == ["$12.00", "$6.00"]
    assert one(rows[0], "[data-aegis-project]") is not None
    none(rows[1], "[data-aegis-project]")


def test_the_steps_page_points_at_the_server_a_project_has(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    card = _card(TestClient(app))
    assert one(card, '[data-deploy-state="has-server"] a').get("href") == PAGE
    none(card, "[data-provision]")


def test_a_deployed_server_points_at_the_dev_overseer_or_ci(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with())
    deployed(monkeypatch, {})
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    for page in (PAGE, NEW):
        card = _card(TestClient(app), page)
        said = text(one(card, '[data-deploy-state="deployed"]'))
        assert "aegis deploy-cd-setup" in said
        none(card, "[data-write]")


def test_without_redis_it_says_the_actions_need_it(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "has_redis", lambda: False)
    card = _card(TestClient(app))
    assert "aegis add redis" in text(one(card, '[data-deploy-state="no-redis"]'))
    none(card, "[data-ask], [data-provision]")  # keys may still be set


def test_without_an_agent_it_shows_how_to_start_one(
    redis: FakeRedis, app: FastAPI
) -> None:
    """One sentence with the command; what the agent is for folded away."""
    del redis.strings[agent.HEARTBEAT]
    card = _card(TestClient(app))
    note = one(card, '[data-deploy-state="no-agent"]')
    (said,) = select(note, ":scope > p")
    assert "aegis deploy-agent" in text(said) and "make serve" in text(said)
    why = one(note, "details[data-agent-why]")
    assert why.get("open") is None
    assert "SSH key" in text(why)
    none(card, "[data-ask], [data-provision]")  # keys may still be set


def test_the_listening_agent_names_the_checkout_it_deploys_from(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every checkout of a project (a worktree, a copy) runs its own agent:
    the server card says whose deploys are about to run."""
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    card = _card(TestClient(app), PAGE)
    assert "/home/ada/my-app" in text(one(card, '[data-deploy-state="ready"]'))
    one(card, '[data-ask="deploy"]')


def test_an_agent_older_than_the_app_is_named_stale(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Started before the CLI learned an action the page asks for: the
    card says restart it, and an ask is refused saying the same, never
    "not an action"."""
    beat = json.loads(redis.strings[agent.HEARTBEAT])
    beat["actions"].remove("account")
    redis.strings[agent.HEARTBEAT] = json.dumps(beat)
    card = _card(TestClient(app))
    stale = one(card, '[data-deploy-state="stale"]')
    assert "make serve" in text(stale)
    assert "pid 4242" in text(one(stale, "[data-agent-said]"))  # the one to stop
    assert _steps(card)[0] == ("agent", "current")
    _sold(redis)
    url = deploy_form.panel_url(
        "account", "digitalocean", size="s-1vcpu-2gb", region="tor1"
    )
    said = text(one(TestClient(app).get(url).text, "[data-account] [data-error]"))
    assert "older than this app" in said
    assert _queued(redis) == []


def test_the_steps_are_read_from_what_is_true(redis: FakeRedis, app: FastAPI) -> None:
    """An agent listening: it is done, said in a line; a domain is
    optional; the server (its cloud, keys and form) is the step at hand."""
    card = _card(TestClient(app))
    assert _steps(card) == [
        ("agent", "done"),
        ("domain", "optional"),
        ("server", "current"),
    ]
    assert "/home/ada/my-app" in text(one(_step(card, "agent"), "[data-summary]"))
    one(_step(card, "server"), "[data-step-body] [data-provision]")


def test_the_domain_step_asks_each_dns_providers_keys(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Optional: without one the server gets an sslip.io name. Each key
    opens the Secrets dialog (saved where .env values are read), which
    comes back here."""
    step = _step(_card(TestClient(app)), "domain")
    assert step.get("data-status") == "optional"
    assert _picker_offers(step, "dns") == ["", "porkbun", "cloudflare"]
    assert _picker_on(step, "dns") == ""  # none until a provider's keys are set
    for provider, keys in (
        ("porkbun", ("PORKBUN_API_KEY", "PORKBUN_SECRET_KEY")),
        ("cloudflare", ("CLOUDFLARE_API_TOKEN",)),
    ):
        dns = one(step, f'[data-dns="{provider}"]')
        for key in keys:
            row = one(dns, f'[data-key="{key}"]')
            if secrets.writable():
                url = overseer_secrets.set_url(key, NEW)
                assert one(row, "button").get("hx-get") == url
            else:
                assert ".env" in text(row)
    assert "sslip.io" in text(step)


def test_with_a_dns_providers_keys_the_domain_step_is_done(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    store.values |= {
        "PORKBUN_API_KEY": "pk1_" + "a" * 20,
        "PORKBUN_SECRET_KEY": "sk1_" + "b" * 20,
    }
    step = _step(_card(TestClient(app)), "domain")
    assert step.get("data-status") == "done"
    assert _picker_on(step, "dns") == "porkbun"
    assert "Porkbun" in text(one(step, "[data-summary]"))


def test_with_one_of_a_pair_of_keys_the_picker_stays_on_its_provider(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    """Saving a key comes back to the page: half way through Porkbun's
    pair it opens on Porkbun still, the other key's row at hand."""
    store.values |= {"PORKBUN_API_KEY": "pk1_" + "a" * 20}
    step = _step(_card(TestClient(app)), "domain")
    assert step.get("data-status") == "optional"
    assert _picker_on(step, "dns") == "porkbun"


def test_without_an_agent_the_steps_after_it_wait(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    del redis.strings[agent.HEARTBEAT]
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    card = _card(TestClient(app))
    assert _steps(card) == [
        ("agent", "current"),
        ("domain", "optional"),
        ("server", "todo"),
    ]
    none(card, "[data-provision]")


def _by_hand(step: Any, way: str, body: bool = True) -> Any:
    """A step's terminal way (``way``), folded away until opened."""
    inside = "[data-step-body] " if body else ""
    folded = one(step, f'{inside}details[data-by-hand="{way}"]')
    assert folded.get("open") is None
    return folded


def _picker_offers(scope: Any, model: str) -> list[str | None]:
    """What a provider picker (its Alpine field, ``model``) offers."""
    return [
        i.get("data-value")
        for i in select(scope, f'[data-picker="{model}"] [data-value]')
    ]


def _picker_on(scope: Any, model: str) -> str | None:
    """What a provider picker opens on."""
    (item,) = select(
        scope, f'[data-picker="{model}"] [data-value][aria-current="true"]'
    )
    return item.get("data-value")


def test_each_step_has_its_terminal_way_folded_under_it(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    """The agent's command, in its note; under each picker, only the picked
    provider's command, with the keys it reads; and, apart, a server of
    your own."""
    beat = redis.strings.pop(agent.HEARTBEAT)  # no agent: its step is open
    started = _step(_card(TestClient(app)), "agent")
    assert text(started).count("aegis deploy-agent") == 1  # its note's, once
    redis.strings[agent.HEARTBEAT] = beat
    card = _card(TestClient(app))
    assert _steps(card)[1:] == [("domain", "optional"), ("server", "current")]
    for step, model, providers in (
        ("domain", "dns", hosting.DNS),
        ("server", "cloud", hosting.PROVISIONABLE),
    ):
        box = _by_hand(_step(card, step), model)
        for p in providers:
            said = text(one(box, f"[x-show=\"{model} === '{p.key}'\"]"))
            assert p.command in said and all(name in said for name in p.secrets)
    # A server of your own: under the new-server form's heading.
    form = one(_step(card, "server"), '[data-provision="digitalocean"]')
    heading = one(form, "[data-provision-heading]")
    own = _by_hand(form, "own", body=False)
    assert own.getprevious() is heading
    assert "aegis deploy-init --host" in text(own) and "aegis deploy" in text(own)


def test_the_server_step_picks_the_cloud_its_keys_and_its_form_follow(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    """One cloud at a time, as DNS is: it opens on the first whose token is
    set (here both are: Hetzner's the app's, DigitalOcean's the agent's);
    the picked one's keys, then its new-server form."""
    store.values["HCLOUD_TOKEN"] = "hetzner-token-from-the-app"
    card = _card(TestClient(app))
    server = _step(card, "server")
    one(card, '[data-picker="cloud"]')  # one place to pick it
    assert _picker_offers(server, "cloud") == [p.key for p in hosting.PROVISIONABLE]
    assert _picker_on(server, "cloud") == "hetzner"
    for p in hosting.PROVISIONABLE:
        cloud = one(server, f'[data-for="{p.key}"]')
        assert cloud.get("x-show") == f"cloud === '{p.key}'"
        one(cloud, f'[data-cloud="{p.key}"] [data-key="{p.token}"]')
        shown = one(cloud, "[data-provision]")
        assert shown.get("data-provision") == p.key
        # Loaded only once its cloud is picked and it shows, not on opening
        # the page for every cloud at once.
        assert shown.get("hx-trigger") == "intersect once"


def test_a_cloud_without_its_token_says_so_on_the_server_step(
    redis: FakeRedis, app: FastAPI
) -> None:
    """The agent holds DigitalOcean's only: Hetzner's form would fail, so
    its key is asked for in its place."""
    server = _step(_card(TestClient(app)), "server")
    hetzner = one(server, '[data-for="hetzner"]')
    none(hetzner, "[data-provision]")
    assert "not set" in text(one(hetzner, '[data-key="HCLOUD_TOKEN"]'))


def test_a_new_server_on_each_provider_the_agent_has_a_token_for(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Each loads its form from the provider's catalog (``CATALOG_URL``)."""
    card = _card(TestClient(app))
    (form,) = select(card, "[data-provision]")
    assert form.get("data-provision") == "digitalocean"
    assert form.get("data-write") is not None
    assert (form.get("hx-get"), form.get("hx-trigger")) == (
        CATALOG_URL,
        "intersect once",
    )
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
    one(form, "[data-waiting] progress:not([value])")  # a bar, moving
    assert form.get("hx-get") == f"{CATALOG_URL}?job={request['job_id']}"
    assert form.get("hx-trigger") == "every 1s"


def test_a_poll_while_the_agent_works_leaves_the_bar_running(
    redis: FakeRedis, app: FastAPI
) -> None:
    """No content, so htmx swaps nothing: the bar keeps moving instead of
    starting over each second, and the panel polls again."""
    client = TestClient(app)
    _form(client)
    (request,) = _queued(redis)
    waiting = client.get(CATALOG_URL, params={"job": request["job_id"]})
    assert (waiting.status_code, waiting.text) == (204, "")
    _sold(redis)
    fit = one(client.get(FIT_URL, params={"size": "s-1vcpu-2gb"}).text, "[data-fit]")
    one(fit, "[data-waiting] progress:not([value])")
    (_, measuring) = _queued(redis)
    polled = client.get(
        FIT_URL, params={"size": "s-1vcpu-2gb", "job": measuring["job_id"]}
    )
    assert polled.status_code == 204


def test_each_picker_wears_its_providers_logos_and_nothing_else_does(
    redis: FakeRedis, app: FastAPI
) -> None:
    """So it is plain which account the server is bought on: the logos are
    the pickers', each offered provider and the one picked."""
    server = _step(_card(TestClient(app)), "server")
    for p in hosting.PROVISIONABLE:
        item = one(server, f'[data-picker="cloud"] [data-value="{p.key}"]')
        assert p.domain in one(item, "img").get("src")
        # The mark follows a pick, not just the one the page opened on.
        assert f"cloud === '{p.key}'" in item.get("x-bind:aria-current")
    _sold(redis)
    none(_form(TestClient(app)), "img")


def test_a_poll_for_a_request_that_is_gone_stops_and_offers_to_ask_again(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Its job expired or was never picked up: said, with a way to ask
    again, never a bar that moves forever."""
    form = _form(TestClient(app), job="c" * 32)
    assert "ask again" in text(one(form, "[data-error]"))
    assert one(form, "[data-retry]").get("hx-get") == CATALOG_URL
    _sold(redis)
    fit = _fit(TestClient(app), "s-1vcpu-2gb", job="c" * 32)
    assert "ask again" in text(one(fit, "[data-error]"))
    assert one(fit, "[data-retry]").get("hx-get") == f"{FIT_URL}?size=s-1vcpu-2gb"


def test_a_poll_after_the_agent_stopped_says_so(redis: FakeRedis, app: FastAPI) -> None:
    client = TestClient(app)
    _form(client)
    (request,) = _queued(redis)
    del redis.strings[agent.HEARTBEAT]
    form = _form(client, job=request["job_id"])
    assert "No deploy agent is listening" in text(one(form, "[data-error]"))


def test_a_stack_without_redis_is_said_not_a_server_error(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Redis to reach the agent through: a refusal saying so, like Redis
    not answering, wherever the agent is asked (never a 500)."""
    monkeypatch.setattr(agent, "has_redis", lambda: False)

    def no_client() -> None:
        raise AssertionError("no Redis to make a client for")

    monkeypatch.setattr(agent, "_client", no_client)
    response = TestClient(app).get(deploy_form.ROLLBACK)
    assert response.status_code == 200
    assert "no Redis" in text(one(response.text, "[data-rollback] [data-error]"))


def test_redis_not_answering_is_said_not_a_server_error(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A panel says so (htmx swaps nothing on a 500, so its bar would just
    keep moving), and so does the card."""
    refused = pytest.importorskip("redis.exceptions").ConnectionError

    class Down:
        async def get(self, *_args: Any) -> None:
            raise refused("Connection refused")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(agent, "_client", lambda: Down())
    response = TestClient(app).get(FIT_URL, params={"size": "s-1vcpu-2gb"})
    assert response.status_code == 200
    said = text(one(response.text, "[data-fit] [data-error]"))
    assert "Redis is not answering" in said
    card = _card(TestClient(app))
    assert "Redis is not answering" in text(
        one(card, '[data-deploy-state="unreachable"]')
    )


def test_once_the_agent_answers_the_form_fills_in(
    redis: FakeRedis, app: FastAPI
) -> None:
    client = TestClient(app)
    _form(client)
    (request,) = _queued(redis)
    _sold(redis)
    form = _form(client, job=request["job_id"])
    none(form, ":scope > [data-waiting]")  # its panels may still wait
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
    provider's default size, in its default region, which offers it."""
    _sold(redis)
    form = _form(TestClient(app))
    groups = [g.get("label") for g in select(form, "select[name=size] optgroup")]
    assert groups == ["Basic", "General Purpose"]
    assert _options(form, "size")[:3] == [
        ("s-1vcpu-1gb", "1.0 GB · 1 vCPU · 25 GB"),
        ("s-1vcpu-2gb", "2.0 GB · 1 vCPU · 50 GB"),
        ("s-2vcpu-4gb", "4.0 GB · 2 vCPU · 80 GB"),
    ]
    assert chosen(form, "select[name=size]") == "s-1vcpu-2gb"
    assert _options(form, "region") == [
        ("fra1", "Frankfurt 1 (fra1)"),
        ("tor1", "Toronto 1 (tor1)"),
    ]
    assert chosen(form, "select[name=region]") == "tor1"
    assert "$12.00 a month" in text(one(form, "[data-price]"))
    assert form.get("data-write") is not None


def test_a_size_reloads_the_form_with_the_regions_that_offer_it(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    form = _form(TestClient(app), size="s-1vcpu-1gb", region="tor1")
    assert "change" in form.get("hx-trigger") and form.get("hx-get") == CATALOG_URL
    assert [slug for slug, _ in _options(form, "region")] == ["fra1", "nyc3"]
    # Neither tor1 (asked, and the default) offers it: the first by name.
    assert chosen(form, "select[name=region]") == "fra1"
    assert "$6.00 a month" in text(one(form, "[data-price]"))


def test_a_provider_selling_nothing_says_so(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis, SOLD | {"sizes": []})
    form = _form(TestClient(app))
    assert "DigitalOcean offers no server" in text(one(form, "[data-error]"))


def test_the_form_loads_whether_its_size_fits(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis)
    fit = one(_form(TestClient(app)), "[data-fit]")
    assert fit.get("hx-get") == deploy_form.panel_url(
        "fit", "digitalocean", size="s-1vcpu-2gb"
    )
    assert fit.get("hx-trigger") == "load"


def test_the_form_shows_what_the_account_runs_and_the_total_with_this_one(
    redis: FakeRedis, app: FastAPI
) -> None:
    """What the account's servers cost a month, with the server being
    bought, and what it has spent this month: every amount money, whole
    units as the provider says them (never cents). The servers themselves
    are the Overview's to list."""
    _sold(redis)
    _accounted(redis)
    account = one(_form(TestClient(app)), "[data-account]")
    said = text(account)
    assert "Already in your account: 2 servers, $18.00 a month" in said
    assert "With this one: $30.00 a month" in said
    assert "$23.17" in text(one(account, "[data-month-to-date]"))
    none(account, "table, img")  # the cloud picker wears the logo here


def test_without_billing_read_the_account_says_which_scope(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    _accounted(redis, ACCOUNT | {"month_to_date": None, "missing": ["billing:read"]})
    account = one(_form(TestClient(app)), "[data-account]")
    none(account, "[data-month-to-date]")
    assert "billing:read" in text(one(account, "[data-missing-scope]"))


def test_an_empty_account_says_so(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis)
    _accounted(redis, ACCOUNT | {"servers": []})
    said = text(one(_form(TestClient(app)), "[data-account]"))
    assert "nothing running" in said and "With this one: $12.00 a month" in said


def test_without_the_account_the_agent_is_asked(redis: FakeRedis, app: FastAPI) -> None:
    """In the background, for the size and region picked (the total
    includes this one)."""
    _sold(redis)
    placeholder = one(_form(TestClient(app)), "[data-account]")
    url = deploy_form.panel_url(
        "account", "digitalocean", size="s-1vcpu-2gb", region="tor1"
    )
    assert placeholder.get("hx-get") == url
    response = TestClient(app).get(url)
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == (
        "account",
        {"provider": "digitalocean"},
    )
    assert agent.LAST not in redis.strings
    one(response.text, "[data-account] [data-waiting]")


def test_with_the_stack_measured_the_form_says_at_once(
    redis: FakeRedis, app: FastAPI
) -> None:
    """No second request, and nothing to wait on while sizes change."""
    _sold(redis)
    _measured(redis)
    fit = one(_form(TestClient(app)), "[data-fit]")
    assert fit.get("hx-get") is None
    one(fit, '[data-fit-row="memory"]')


def test_without_a_footprint_the_agent_measures_the_stack(
    redis: FakeRedis, app: FastAPI
) -> None:
    """In the background, like the catalog; the fit waits on it."""
    _sold(redis)
    fit = _fit(TestClient(app), "s-1vcpu-2gb")
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == ("footprint", {})
    assert agent.LAST not in redis.strings
    one(fit, "[data-waiting]")
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
    assert "If every service grew to its limit" in why
    assert "worker-system (1.0 GB)" in why and "webserver (768.0 MB)" in why
    assert _tone(_row(fit, "cpu")) == "muted"
    assert _tone(_row(fit, "disk")) == "ok"
    assert one(fit, "[data-verdict] [data-tone]").get("data-tone") == "warn"


def test_one_service_limited_past_the_servers_cpus_does_not_fit(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Docker refuses to start a container limited to more CPUs than the
    machine has: not slower, not started at all."""
    _sold(redis)
    services = [dict(s) for s in FOOTPRINT["services"]]
    services[0]["cpus"] = 2.0  # the webserver
    _measured(redis, FOOTPRINT | {"services": services})
    fit = _fit(TestClient(app), "s-1vcpu-2gb")
    cpu = _row(fit, "cpu")
    assert _tone(cpu) == "error"
    assert "webserver (2 CPUs)" in text(one(cpu, "[data-why]"))
    assert one(fit, "[data-verdict] [data-tone]").get("data-tone") == "error"


def test_the_limits_are_drawn_service_by_service(
    redis: FakeRedis, app: FastAPI
) -> None:
    """One dashed segment per service, biggest first, each named with its
    limit: the total is the services' together, none of them alone."""
    _sold(redis)
    _measured(redis)
    memory = _row(_fit(TestClient(app), "s-1vcpu-2gb"), "memory")
    segments = select(memory, "[data-segment]")
    assert [s.get("data-segment") for s in segments] == [
        "worker-system",
        "webserver",
        "scheduler",
        "redis",
        "traefik",
        "socket-proxy",
    ]
    assert text(one(segments[0], "title")) == "worker-system: up to 1.0 GB"


def test_a_4_gb_server_has_room(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis)
    _measured(redis)
    fit = _fit(TestClient(app), "s-2vcpu-4gb")
    assert _tone(_row(fit, "memory")) == "ok"
    assert one(fit, "[data-verdict] [data-tone]").get("data-tone") == "ok"


def test_a_server_too_small_for_what_runs_today_is_red(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    _measured(redis)
    fit = _fit(TestClient(app), "s-1vcpu-1gb")
    memory = _row(fit, "memory")
    assert _tone(memory) == "error"
    assert "now" in text(one(memory, "[data-why]"))
    assert one(fit, "[data-verdict] [data-tone]").get("data-tone") == "error"


def test_without_the_default_size_the_cheapest_with_2_gb_is_offered(
    redis: FakeRedis, app: FastAPI
) -> None:
    sizes = [s for s in SOLD["sizes"] if s["slug"] != "s-1vcpu-2gb"]
    _sold(redis, SOLD | {"sizes": sizes})
    assert chosen(_form(TestClient(app)), "select[name=size]") == "s-2vcpu-4gb"


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
    for verb in ("deploy", "backup"):
        assert one(card, f'[data-ask="{verb}"]').get("data-write") is not None
    # The backups a rollback picks from load on their own (no list to ask).
    assert one(card, "[data-rollback]").get("hx-get") == deploy_form.ROLLBACK
    none(card, '[data-ask="backups"]')
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
    assert _picker_on(card, "cloud") == "hetzner"
    held = one(card, '[data-cloud="hetzner"] [data-key="HCLOUD_TOKEN"]')
    assert "not set" not in text(held)


def test_with_no_token_anywhere_it_says_where_to_set_it(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    """Each provider's token, set from here (the Secrets dialog, which comes
    back) where the app keeps secrets, else named for .env."""
    _agent_holds(redis)
    card = _card(TestClient(app))
    none(card, "[data-provision]")
    for p in hosting.PROVISIONABLE:
        missing = one(card, f'[data-cloud="{p.key}"] [data-key="{p.token}"]')
        assert "not set" in text(missing)
        if secrets.writable():
            url = overseer_secrets.set_url(p.token, NEW)
            assert one(missing, "button").get("hx-get") == url
        else:
            assert ".env" in text(missing)
            none(missing, "button")


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


def test_create_server_is_off_until_the_price_is_typed(
    redis: FakeRedis, app: FastAPI
) -> None:
    """The browser holds the form (and dims its button) until the typed
    price is the one shown; the server checks again."""
    _sold(redis)
    typed = one(_form(TestClient(app)), "form input[name=typed]")
    assert (typed.get("pattern"), typed.get("required")) == (r"12\.00", "")


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


PORKBUN = {
    "PORKBUN_API_KEY": "pk1_" + "a" * 24,
    "PORKBUN_SECRET_KEY": "sk1_" + "b" * 24,
}


def test_a_new_server_on_a_domain_carries_its_dns_providers_keys(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    """The Domain step's picker is the one choice: the form carries it (no
    second select of its own); the keys travel with the request, outside
    its audited arguments."""
    store.values |= PORKBUN
    _sold(redis)
    form = _form(TestClient(app))
    none(form, "select[name=dns]")
    assert one(form, "input[type=hidden][name=dns]").get("x-bind:value") == "dns"
    named = {"typed": "12.00", "domain": "app.example.com", "dns": "porkbun"}
    TestClient(app).post(f"{actions.PARTIALS}/provision", data=PICKED | named)
    (request,) = _queued(redis)
    assert request["args"]["dns"] == "porkbun"
    assert request["dns_keys"] == PORKBUN
    assert not set(PORKBUN.values()) & set(request["args"].values())


def test_who_may_reach_the_overseer_is_asked_on_the_form(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Networks, checked as the agent checks them; stamped on the server's
    .env at each deploy, so the Overseer there answers you."""
    _sold(redis)
    one(_form(TestClient(app)), "input[name=allowlist]")
    url = f"{actions.PARTIALS}/provision"
    response = TestClient(app).post(
        url, data=PICKED | {"typed": "12.00", "allowlist": "my house"}
    )
    assert triggers(response)["toast"]["tone"] == "error"
    assert not _queued(redis)
    TestClient(app).post(
        url, data=PICKED | {"typed": "12.00", "allowlist": "203.0.113.9/32"}
    )
    (request,) = _queued(redis)
    assert request["args"]["allowlist"] == "203.0.113.9/32"


# A stack without a database has no DATABASE_URL, and nothing to bring.
WITH_A_DATABASE = pytest.mark.skipif(
    not hasattr(settings, "DATABASE_URL"), reason="no database in this stack"
)


@WITH_A_DATABASE
def test_bringing_this_machines_data_is_a_box_on_the_form(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off by default: ticked, the agent copies the SQLite database over
    after the first deploy (``aegis deploy-upload-db``); the box stays
    ticked when a size or region reloads the form."""
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///./data/app.db")
    _sold(redis)
    box = one(_form(TestClient(app)), "input[type=checkbox][name=data]")
    assert box.get("value") == "local" and box.get("checked") is None
    assert (
        one(_form(TestClient(app), data="local"), "input[name=data]").get("checked")
        is not None
    )
    url = f"{actions.PARTIALS}/provision"
    TestClient(app).post(url, data=PICKED | {"typed": "12.00", "data": "local"})
    (request,) = _queued(redis)
    assert request["args"]["data"] == "local"


def test_the_form_keeps_to_what_most_fill_in(redis: FakeRedis, app: FastAPI) -> None:
    """Size, region, a name; the email and who reaches the Overseer folded
    under More options, which most leave as they are."""
    _sold(redis)
    form = _form(TestClient(app))
    more = one(form, "details[data-more]")
    for name in ("email", "allowlist"):
        one(more, f"input[name={name}]")
    for name in ("size", "region", "domain"):
        none(more, f"[name={name}]")
        one(form, f"[name={name}]")


def test_whether_it_fits_is_its_verdict_with_the_bars_folded(
    redis: FakeRedis, app: FastAPI
) -> None:
    _sold(redis)
    _measured(redis)
    fit = _fit(TestClient(app), "s-1vcpu-2gb")
    folded = one(fit, "details[data-fit-details]")
    one(one(folded, "summary"), "[data-verdict]")
    one(folded, '[data-fit-row="memory"]')


@WITH_A_DATABASE
def test_without_sqlite_there_is_no_data_to_bring(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://db/app")
    _sold(redis)
    none(_form(TestClient(app)), "input[name=data]")


def test_without_a_domain_no_dns_keys_travel(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    """A provider picked but no name to give: nothing uses the keys."""
    store.values |= PORKBUN
    _sold(redis)
    data = PICKED | {"typed": "12.00", "dns": "porkbun"}
    TestClient(app).post(f"{actions.PARTIALS}/provision", data=data)
    (request,) = _queued(redis)
    assert "dns_keys" not in request


def test_destroying_a_record_from_before_its_provider_was_named_sends_cloudflares(
    redis: FakeRedis, store: FakeStore, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Records were Cloudflare's only then: the CLI reads them so too."""
    store.values["CLOUDFLARE_API_TOKEN"] = "cf-token-from-the-app-0000"
    made = READY | {"dns": {"zone_id": "zone1", "record_id": "rec1"}}
    deployed(monkeypatch, {"server": BOX, "provision": made})
    TestClient(app).post(f"{actions.PARTIALS}/destroy", data={"confirm": "my-app"})
    (request,) = _queued(redis)
    assert request["dns_keys"] == {"CLOUDFLARE_API_TOKEN": "cf-token-from-the-app-0000"}


def test_a_key_set_in_env_is_changed_there_not_replaced_here(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Secrets page's own rule: a saved value never beats .env."""
    if not secrets.writable():
        pytest.skip("no secrets store to replace into")
    monkeypatch.setitem(settings.__dict__, "HCLOUD_TOKEN", "hetzner-token-in-env")
    row = one(
        _card(TestClient(app)), '[data-cloud="hetzner"] [data-key="HCLOUD_TOKEN"]'
    )
    assert "Change it in .env" in text(row)
    none(row, "button[hx-get]")


def test_a_destroy_carries_the_keys_its_record_was_made_with(
    redis: FakeRedis, store: FakeStore, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.values |= PORKBUN
    made = READY | {"dns": {"provider": "porkbun", "zone_id": "example.com"}}
    deployed(monkeypatch, {"server": BOX, "provision": made})
    TestClient(app).post(f"{actions.PARTIALS}/destroy", data={"confirm": "my-app"})
    (request,) = _queued(redis)
    assert request["dns_keys"] == PORKBUN


def test_an_agent_from_before_dns_keys_is_named_stale(
    redis: FakeRedis, app: FastAPI
) -> None:
    """It would run a provision without the keys it was sent."""
    beat = json.loads(redis.strings[agent.HEARTBEAT])
    del beat["revision"]
    redis.strings[agent.HEARTBEAT] = json.dumps(beat)
    one(_card(TestClient(app)), '[data-deploy-state="stale"]')


BACKUPS = [
    {"name": "2026-10-15_014324", "size": "172M", "database": True},
    {"name": "2026-10-14_233051", "size": "27M", "database": False},
]


def test_a_rollback_is_picked_from_the_servers_backups(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only backups the server has, newest first, each saying whether it
    holds the database: nothing to type."""
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    _keep(redis, "backups", {"backups": BACKUPS})
    form = one(TestClient(app).get(deploy_form.ROLLBACK).text, '[data-ask="rollback"]')
    picked = one(form, "select[name=backup]")
    options = select(picked, "option")
    assert [o.get("value") for o in options] == [b["name"] for b in BACKUPS]
    assert "no database" in text(options[1]) and "no database" not in text(options[0])
    none(form, "input[name=backup]")


def test_while_the_backups_are_looked_up_the_panel_waits(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    panel = one(TestClient(app).get(deploy_form.ROLLBACK).text, "[data-rollback]")
    one(panel, "[data-waiting]")
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == ("backups", {})


def test_a_server_without_backups_says_so(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    _keep(redis, "backups", {"backups": []})
    panel = one(TestClient(app).get(deploy_form.ROLLBACK).text, "[data-rollback]")
    none(panel, '[data-ask="rollback"]')
    assert "Back up now" in text(panel)


@pytest.mark.parametrize("backup", ["2020-01-01_000000", ""])
def test_a_rollback_to_a_backup_the_server_has_not_is_refused(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch, backup: str
) -> None:
    """Asked by hand or from a stale page, a name not in the list never
    reaches the agent; one in it does."""
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    _keep(redis, "backups", {"backups": BACKUPS})
    client = TestClient(app)
    client.post(f"{actions.PARTIALS}/rollback", data={"backup": backup})
    assert _queued(redis) == []
    client.post(f"{actions.PARTIALS}/rollback", data={"backup": BACKUPS[1]["name"]})
    (request,) = _queued(redis)
    assert request["args"] == {"backup": BACKUPS[1]["name"]}


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


def test_a_provision_that_stopped_offers_resume_and_folds_away_the_rest(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the job on the page: no pickers, no form; delete and the output
    each folded under their own disclosure."""
    deployed(monkeypatch, {"provision": READY | {"status": "provisioning"}})
    lines = {"lines": ["Created server 77", "SSH on 203.0.113.7 did not come up"]}
    _job(redis, "provision", lines, error="aegis deploy-provision failed (exit 1)")
    page = page_html(TestClient(app), NEW)
    none(page, "[data-steps]")
    panel = one(page, '[data-deploy-job="provision"]')
    assert one(panel, '[data-ask="resume"]').get("data-write") is not None
    destroy = one(panel, 'details[data-delete] [data-ask="destroy"]')
    assert one(destroy, "input[name=confirm]").get("pattern") == "my-app"
    output = one(panel, "details[data-output] [data-lines]")
    assert "SSH on 203.0.113.7" in text(output)
    copied = one(panel, "details[data-output] [data-copy]").get("data-copy")
    assert copied == "\n".join(lines["lines"])


def test_one_stopped_so_long_ago_its_job_is_gone_still_offers_resume(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = {"status": "provisioning", "error": "SSH on 203.0.113.7 timed out."}
    deployed(monkeypatch, {"provision": READY | stopped})
    page = page_html(TestClient(app), NEW)
    none(page, "[data-steps]")
    panel = one(page, '[data-deploy-job="provision"]')
    assert text(one(panel, "[data-error]")) == stopped["error"]  # why, kept
    one(panel, '[data-ask="resume"]')
    one(panel, 'details[data-delete] [data-ask="destroy"]')


def test_a_failed_delete_of_one_stopped_still_offers_resume(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its server still half made and billed: the way on stays on the page."""
    deployed(monkeypatch, {"provision": READY | {"status": "provisioning"}})
    _job(redis, "destroy", {"lines": []}, error="aegis deploy-destroy failed (exit 1)")
    panel = one(page_html(TestClient(app), NEW), '[data-deploy-job="destroy"]')
    one(panel, '[data-ask="resume"]')


def test_resume_asks_the_agent_for_the_provision_on_record(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(app)
    url = f"{actions.PARTIALS}/resume"
    deployed(monkeypatch, {"provision": READY})
    assert triggers(client.post(url))["toast"]["tone"] == "error"
    assert not _queued(redis)
    deployed(monkeypatch, {"provision": READY | {"status": "provisioning"}})
    response = client.post(url)
    (request,) = _queued(redis)
    assert (request["action"], request["args"]) == ("resume", {})
    one(response.text, '[data-deploy-job="resume"]')


PLAN = list(PROVISION_STEPS)


def _stages(panel: Any) -> dict[str, str]:
    """The step bar: each step's title and where it stands."""
    return {
        text(li): li.get("data-status")
        for li in select(one(panel, "[data-stages]"), "[data-stage]")
    }


def test_a_server_being_created_shows_its_steps_as_they_go(
    redis: FakeRedis, app: FastAPI
) -> None:
    progress = {"steps": PLAN, "at": "boot"}
    _job(redis, "provision", {"lines": ["Waiting"], "progress": progress}, running=True)
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    page = page_html(TestClient(app), NEW)
    none(page, "[data-steps]")  # only the job while it runs
    job = '[data-deploy-job="provision"]'
    for panel in (one(frame_html(frame), job), one(page, job)):
        assert _stages(panel) == {
            "Create the server": "done",
            "First boot": "current",
            "Point the name": "todo",
            "Deploy": "todo",
            "Bring my data": "todo",
        }
        none(panel, '[data-ask="resume"]')
    assert one(page, '[data-stage="boot"]').get("aria-current") == "step"


def test_a_failed_provision_marks_the_step_it_stopped_at(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployed(monkeypatch, {"provision": READY | {"status": "provisioning"}})
    progress = {"steps": PLAN[:4], "at": "dns"}
    _job(redis, "provision", {"lines": [], "progress": progress}, error="exit 1")
    panel = one(page_html(TestClient(app), NEW), '[data-deploy-job="provision"]')
    assert list(_stages(panel).values()) == ["done", "done", "failed", "todo"]


def test_a_job_that_marks_no_steps_has_no_step_bar(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Other actions, and an agent older than the step bar."""
    _job(redis, "provision", {"lines": ["Done"]})
    panel = one(page_html(TestClient(app), NEW), '[data-deploy-job="provision"]')
    none(panel, "[data-stages]")


def test_a_backup_shows_its_steps_as_they_go(redis: FakeRedis) -> None:
    progress = {"steps": ["database", "files", "documents"], "at": "files"}
    _job(redis, "backup", {"lines": [], "progress": progress}, running=True)
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    panel = one(frame_html(frame), '[data-deploy-job="backup"]')
    assert _stages(panel) == {
        "Database": "done",
        "Code and settings": "current",
        "Documents": "todo",
    }
    # A backup is no server being made: it stays on the Overview.
    assert not actions.creating({"action": "backup", "status": "running"})


def test_steps_a_job_does_not_declare_draw_no_bar(redis: FakeRedis) -> None:
    """An older CLI, whose deploy let its backup mark the bar: a deploy's
    bar never shows a backup's steps."""
    progress = {"steps": ["database", "files", "documents"], "at": "files"}
    _job(redis, "deploy", {"lines": [], "progress": progress}, running=True)
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    none(one(frame_html(frame), '[data-deploy-job="deploy"]'), "[data-stages]")


def test_a_deploy_shows_its_steps_as_they_go(redis: FakeRedis) -> None:
    progress = {"steps": ["backup", "upload", "build", "health"], "at": "build"}
    _job(redis, "deploy", {"lines": [], "progress": progress}, running=True)
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    panel = one(frame_html(frame), '[data-deploy-job="deploy"]')
    assert _stages(panel) == {
        "Back up": "done",
        "Send the code": "done",
        "Build and start": "current",
        "Check it answers": "todo",
    }


def test_while_a_job_runs_the_card_asks_for_nothing_else(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its every control sits under the lock (``data-locks``: greyed while
    the streamed job says it runs, lifted when it ends), and a request
    sent anyway is refused: the agent would only run it after."""
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    _keep(redis, "backups", {"backups": BACKUPS})
    _job(redis, "deploy", {"lines": []}, running=True)
    page = page_html(TestClient(app), PAGE)
    lock = one(page, "[data-locks]")
    one(lock, '[data-deploy-job="deploy"][data-status="running"]')
    assert len(select(lock, "[data-write]")) == len(select(page, "[data-write]")) > 2
    client = TestClient(app)
    client.post(f"{actions.PARTIALS}/backup")
    client.post(f"{actions.PARTIALS}/rollback", data={"backup": BACKUPS[0]["name"]})
    assert _queued(redis) == []


DEPLOYS = [
    {
        "build_id": "1c956eef",
        "started_at": "2026-10-15T03:16:40",
        "deployed_by": "Ada <ada@example.org>",
        "deployed_from": "ada-laptop",
        "health": "passed",
        "backup": "2026-10-15_031418",
        "rolled_back_to": None,
    }
]


def test_on_this_machine_the_history_is_the_servers(
    redis: FakeRedis, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The protocol's ``history``: asked of the agent, waiting meanwhile."""
    deployed(monkeypatch, {"server": BOX, "provision": READY})
    section = one(page_html(TestClient(app), f"{PAGE}/history"), "[data-history]")
    assert section.get("hx-get") == deploy_form.HISTORY
    one(TestClient(app).get(deploy_form.HISTORY).text, "[data-history] [data-waiting]")
    (request,) = _queued(redis)
    assert request["action"] == "history"

    _keep(redis, "history", {"deploys": DEPLOYS})
    (row,) = select(
        TestClient(app).get(deploy_form.HISTORY).text, "#deployments-history tbody tr"
    )
    assert "1c956eef" in text(row) and "Ada" in text(row) and "passed" in text(row)


def test_the_newest_job_streams(redis: FakeRedis) -> None:
    _job(redis, "backup", {"lines": ["Backup complete"]})
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    assert frame.startswith(f"event: {actions.EVENT}")
    assert "Backup complete" in frame


def test_every_action_the_card_asks_is_titled() -> None:
    """``TITLES`` is the card's actions: the protocol's that are not kept."""
    asked = {a for a in PROTOCOL["actions"] if not is_kept(a)}
    assert set(actions.TITLES) == asked
