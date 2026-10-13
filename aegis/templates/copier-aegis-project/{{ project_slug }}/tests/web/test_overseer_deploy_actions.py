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
from app.components.deploy.protocol import PROTOCOL, kept_key
from app.components.web_frontend import overseer_deploy_actions as actions
from app.components.web_frontend import overseer_secrets
from app.core.config import settings
from app.services.system import hosting
from app.services.system.job_store import RedisJobStore
from tests._audit import recording
from tests._fake_redis import FakeRedis
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests._secret_settings import FakeStore, use_store
from tests.web.dom import chosen, none, one, select, table_rows, text, triggers
from tests.web.overseer import page_html, sent_events, sign_in, status_with

PAGE = "/overseer/deployments"
NEW = f"{PAGE}/new"  # the steps to a new server
CARD = "#card-deploy"
BOX = {"host": "203.0.113.7", "user": "root", "path": "/opt/my-app"}
READY = {"provider": "digitalocean", "server_name": "my-app", "status": "ready"}
TOKEN = "dop_v1_from-the-app-wxyz"
CATALOG_URL = actions.panel_path("catalog", "digitalocean")
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
    "data": 1200 * MIB,
    "images": 480 * MIB,
}
FIT_URL = actions.panel_path("fit", "digitalocean")
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
    monkeypatch.setattr(settings, "BUILD_ID", hosting.LOCAL)
    monkeypatch.setattr(agent, "has_redis", lambda: True)
    fake = FakeRedis()
    monkeypatch.setattr(agent, "_client", lambda: fake)
    beat = {
        "host": "laptop",
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


def _picked(form: Any, name: str) -> str | None:
    return chosen(form, f"select[name={name}]")


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


def test_the_overview_shows_every_server_in_each_connected_account(
    redis: FakeRedis, app: FastAPI
) -> None:
    """From what the agent last found (kept a few minutes), so opening the
    page asks the cloud nothing; nothing is being bought, so no total
    with a new one."""
    _accounted(redis)
    account = one(page_html(TestClient(app), PAGE), "[data-account]")
    assert "2 servers, $18.00 a month" in text(account)
    assert "With this one" not in text(account)
    assert not _queued(redis)


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
    assert "make serve" in text(one(card, '[data-deploy-state="stale"]'))
    assert _steps(card)[0] == ("agent", "current")
    _sold(redis)
    url = actions.panel_url(
        "account", "digitalocean", size="s-1vcpu-2gb", region="tor1"
    )
    said = text(one(TestClient(app).get(url).text, "[data-account] [data-error]"))
    assert "older than this app" in said
    assert _queued(redis) == []


def test_the_steps_are_read_from_what_is_true(redis: FakeRedis, app: FastAPI) -> None:
    """An agent listening and a token held: those two are done, each said
    in a line, and the server is the step at hand."""
    card = _card(TestClient(app))
    assert _steps(card) == [
        ("agent", "done"),
        ("where", "done"),
        ("domain", "optional"),
        ("server", "current"),
    ]
    assert "laptop" in text(one(_step(card, "agent"), "[data-summary]"))
    assert "DigitalOcean" in text(one(_step(card, "where"), "[data-summary]"))
    none(_step(card, "where"), "[data-step-body]")
    one(_step(card, "server"), "[data-step-body] [data-provision]")


def test_the_domain_step_asks_each_dns_providers_keys(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Optional: without one the server gets an sslip.io name. Each key
    opens the Secrets dialog (saved where .env values are read), which
    comes back here."""
    step = _step(_card(TestClient(app)), "domain")
    assert step.get("data-status") == "optional"
    for provider, keys in (
        ("porkbun", ("PORKBUN_API_KEY", "PORKBUN_SECRET_KEY")),
        ("cloudflare", ("CLOUDFLARE_API_TOKEN",)),
    ):
        dns = one(step, f'[data-dns="{provider}"]')
        for key in keys:
            setter = one(dns, f'[data-dns-key="{key}"] button')
            assert setter.get("hx-get") == overseer_secrets.set_url(key, NEW)
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
    assert "Porkbun" in text(one(step, "[data-summary]"))


def test_without_an_agent_the_steps_after_it_wait(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    del redis.strings[agent.HEARTBEAT]
    store.values["DIGITALOCEAN_TOKEN"] = TOKEN
    card = _card(TestClient(app))
    assert _steps(card) == [
        ("agent", "current"),
        ("where", "done"),
        ("domain", "optional"),
        ("server", "todo"),
    ]
    none(card, "[data-provision]")


def test_without_a_token_the_where_step_says_how_and_offers_a_server_of_your_own(
    redis: FakeRedis, store: FakeStore, app: FastAPI
) -> None:
    _agent_holds(redis)
    card = _card(TestClient(app))
    assert _steps(card)[1:] == [
        ("where", "current"),
        ("domain", "optional"),
        ("server", "todo"),
    ]
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


def test_the_form_wears_its_providers_logo(redis: FakeRedis, app: FastAPI) -> None:
    """So it is plain which account the server is bought on."""
    heading = one(_form(TestClient(app)), "[data-provision-heading]")
    assert "DigitalOcean" in text(heading)
    assert "digitalocean.com" in one(heading, "img").get("src")


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
    assert _picked(form, "size") == "s-1vcpu-2gb"
    assert _options(form, "region") == [
        ("fra1", "Frankfurt 1 (fra1)"),
        ("tor1", "Toronto 1 (tor1)"),
    ]
    assert _picked(form, "region") == "tor1"
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
    assert _picked(form, "region") == "fra1"
    assert "$6.00 a month" in text(one(form, "[data-price]"))


def test_a_provider_selling_nothing_says_so(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis, SOLD | {"sizes": []})
    form = _form(TestClient(app))
    assert "DigitalOcean offers no server" in text(one(form, "[data-error]"))


def test_the_form_loads_whether_its_size_fits(redis: FakeRedis, app: FastAPI) -> None:
    _sold(redis)
    fit = one(_form(TestClient(app)), "[data-fit]")
    assert fit.get("hx-get") == actions.panel_url(
        "fit", "digitalocean", size="s-1vcpu-2gb"
    )
    assert fit.get("hx-trigger") == "load"


def test_the_form_shows_what_the_account_runs_and_the_total_with_this_one(
    redis: FakeRedis, app: FastAPI
) -> None:
    """Dearest first, aegis's own marked; what they cost a month, with the
    server being bought, and what the account has spent this month: every
    amount money, whole units as the provider says them (never cents)."""
    _sold(redis)
    _accounted(redis)
    account = one(_form(TestClient(app)), "[data-account]")
    said = text(account)
    assert "2 servers, $18.00 a month" in said
    assert "With this one: $30.00 a month" in said
    assert "$23.17" in text(one(account, "[data-month-to-date]"))
    rows = select(account, "tbody tr")
    assert [text(r).split()[0] for r in rows] == ["my-app", "old-box"]
    assert [text(r["A month"]) for r in table_rows(account)] == ["$12.00", "$6.00"]
    assert one(rows[0], "[data-aegis-project]") is not None
    none(rows[1], "[data-aegis-project]")


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
    url = actions.panel_url(
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
    """The form offers the DNS providers whose keys the app holds; the keys
    travel with the request, outside its audited arguments."""
    store.values |= PORKBUN
    _sold(redis)
    assert chosen(_form(TestClient(app)), "select[name=dns]") == "porkbun"
    named = {"typed": "12.00", "domain": "app.example.com", "dns": "porkbun"}
    TestClient(app).post(f"{actions.PARTIALS}/provision", data=PICKED | named)
    (request,) = _queued(redis)
    assert request["args"]["dns"] == "porkbun"
    assert request["dns_keys"] == PORKBUN
    assert not set(PORKBUN.values()) & set(request["args"].values())


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
    panel = one(page_html(TestClient(app), NEW), '[data-deploy-job="provision"]')
    assert "SSH on 203.0.113.7" in text(one(panel, "[data-lines]"))
    destroy = one(panel, '[data-ask="destroy"]')
    assert destroy.get("data-write") is not None
    assert one(destroy, "input[name=confirm]").get("pattern") == "my-app"


def test_the_newest_job_streams(redis: FakeRedis) -> None:
    _job(redis, "backup", {"lines": ["Backup complete"]})
    (frame,) = asyncio.run(sent_events(actions.events(max_frames=1)))
    assert frame.startswith(f"event: {actions.EVENT}")
    assert "Backup complete" in frame


def test_every_action_the_card_asks_is_titled() -> None:
    """``TITLES`` is the card's actions: the protocol's that are not kept."""
    asked = {a for a, spec in PROTOCOL["actions"].items() if "kept" not in spec}
    assert set(actions.TITLES) == asked
