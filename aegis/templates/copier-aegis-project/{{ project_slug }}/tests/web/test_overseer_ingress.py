"""The Overseer Ingress page: Traefik read live from its own API. How a
request travels (entrypoint, router, middlewares, service, servers), then
each of those in full."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_ingress
from app.services.system.models import ComponentStatus
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with

SERVER = "http://172.18.0.5:8000"

TRAEFIK: dict[str, Any] = {
    "version": {"Version": "3.6.1", "Codename": "ramequin"},
    "entrypoints": [
        {"name": "web", "address": ":80"},
        {"name": "traefik", "address": ":8080"},
    ],
    "routers": [
        {
            "name": "webserver@docker",
            "rule": "PathPrefix(`/`)",
            "priority": 15,
            "service": "webserver",
            "entryPoints": ["web"],
            "middlewares": ["webserver-retry@docker"],
            "status": "enabled",
            "provider": "docker",
        },
        {
            "name": "webserver-admin@docker",
            "rule": "PathPrefix(`/dashboard`) || PathPrefix(`/docs`)",
            "priority": 102,
            "service": "webserver",
            "entryPoints": ["web"],
            "middlewares": ["admin-ipallowlist@docker", "webserver-retry@docker"],
            "status": "enabled",
            "provider": "docker",
        },
        {
            "name": "api@internal",
            "rule": "PathPrefix(`/api`)",
            "priority": 9223372036854775806,
            "service": "api@internal",
            "entryPoints": ["traefik"],
            "status": "enabled",
            "provider": "internal",
        },
    ],
    "services": [
        {
            "name": "webserver@docker",
            "loadBalancer": {"servers": [{"url": SERVER}]},
            "serverStatus": {SERVER: "UP"},
            "status": "enabled",
            "provider": "docker",
            "usedBy": ["webserver@docker", "webserver-admin@docker"],
            "type": "loadbalancer",
        },
        {
            "name": "api@internal",
            "status": "enabled",
            "provider": "internal",
            "usedBy": ["api@internal"],
        },
    ],
    "middlewares": [
        {
            "name": "webserver-retry@docker",
            "type": "retry",
            "retry": {"attempts": 5, "initialInterval": "2s"},
            "status": "enabled",
            "provider": "docker",
            "usedBy": ["webserver@docker", "webserver-admin@docker"],
        },
        {
            "name": "admin-ipallowlist@docker",
            "type": "ipallowlist",
            "ipAllowList": {"sourceRange": ["0.0.0.0/0"]},
            "status": "enabled",
            "provider": "docker",
            "usedBy": ["webserver-admin@docker"],
        },
    ],
}

INGRESS = ComponentStatus(
    name="ingress",
    message="Traefik active: 3 routers, 2 services",
    metadata={"available": True, "api_url": "http://traefik:8080", "version": "3.6.1"},
)


def _serve(monkeypatch: pytest.MonkeyPatch, data: dict[str, Any] | Exception) -> None:
    async def fetch() -> dict[str, Any]:
        if isinstance(data, Exception):
            raise data
        return data

    monkeypatch.setattr(overseer_ingress, "fetch_traefik", fetch)


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(INGRESS))
    _serve(monkeypatch, TRAEFIK)
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "") -> str:
    response = client.get(
        "/overseer/components/ingress" + (f"/{section}" if section else "")
    )
    assert response.status_code == 200
    return response.text


def test_sections(client: TestClient) -> None:
    assert [text(a) for a in select(_get(client), "#overseer-subnav nav a")] == [
        "Overview",
        "Routers",
        "Services",
        "Middlewares",
        "Container",
    ]


def test_overview_counts_what_traefik_runs(client: TestClient) -> None:
    figures = {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(_get(client), "#ingress-figures > div")
    }
    assert figures["Routers"] == "3"
    assert figures["Services"] == "2"
    assert figures["Middlewares"] == "2"
    assert figures["Entrypoints"] == "2"


def test_each_app_router_shows_how_a_request_travels(client: TestClient) -> None:
    flow = one(_get(client), "[data-flow='webserver']")
    steps = [text(s) for s in select(flow, "[data-step-label]")]
    assert steps == [
        "web",
        "PathPrefix(`/`)",
        "webserver-retry",
        "webserver",
        f"{SERVER}",
    ]


def test_traefiks_own_routers_are_not_drawn_as_app_traffic(client: TestClient) -> None:
    assert not select(_get(client), "[data-flow='api']")


def _row(html: str, table: str, name: str) -> str:
    rows = [text(r) for r in select(html, f"#{table} tbody tr")]
    return next(r for r in rows if r.split()[0] == name)


def test_routers_show_which_wins_on_each_entrypoint(client: TestClient) -> None:
    """Traefik tries the highest priority first (by default the longest
    rule), so /docs reaches webserver-admin before webserver's /."""
    html = _get(client, "routers")
    names = [text(r).split()[0] for r in select(html, "#ingress-routers tbody tr")]
    assert names == ["api", "webserver-admin", "webserver"]
    admin = _row(html, "ingress-routers", "webserver-admin")
    assert "PathPrefix(`/dashboard`) || PathPrefix(`/docs`)" in admin
    assert "admin-ipallowlist" in admin and "102" in admin
    assert "Highest" in _row(html, "ingress-routers", "api")


def _cells(html: str, table: str, name: str) -> tuple[Any, list[Any]]:
    """A row by the name it starts with, and its warning tags."""
    row = [r for r in select(html, f"#{table} tbody tr") if text(r).startswith(name)][0]
    return row, select(row, "[data-warning]")


def _status(row: Any) -> str:
    return text(select(row, "td")[-1])


def test_traefiks_own_api_without_auth_is_flagged_beside_its_name(
    client: TestClient,
) -> None:
    """Posture is its own tag; the status still says the router runs."""
    row, warnings = _cells(_get(client, "routers"), "ingress-routers", "api")
    assert [text(w) for w in warnings] == ["no auth"]
    assert warnings[0].get("data-tone") == "warn"
    assert _status(row) == "enabled"


def test_services_mark_each_server_up_or_down(client: TestClient) -> None:
    html = _get(client, "services")
    badge = one(html, f"[data-server='{SERVER}'] [data-tone]")
    assert text(badge) == "UP" and badge.get("data-tone") == "ok"


def test_a_down_server_is_marked_as_an_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = {
        **TRAEFIK,
        "services": [{**TRAEFIK["services"][0], "serverStatus": {SERVER: "DOWN"}}],
    }
    _serve(monkeypatch, down)
    badge = one(_get(client, "services"), f"[data-server='{SERVER}'] [data-tone]")
    assert badge.get("data-tone") == "error"


def test_middlewares_show_type_settings_and_users(client: TestClient) -> None:
    retry = _row(_get(client, "middlewares"), "ingress-middlewares", "webserver-retry")
    assert "retry" in retry and "attempts 5" in retry and "2" in retry


def test_an_unreachable_traefik_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, ConnectionError("traefik:8080 refused"))
    assert "refused" in text(one(_get(client, "routers"), "[role=alert]"))


def test_an_allowlist_that_allows_everyone_is_tagged(client: TestClient) -> None:
    row, warnings = _cells(
        _get(client, "middlewares"), "ingress-middlewares", "admin-ipallowlist"
    )
    assert [text(w) for w in warnings] == ["allows all"]
    assert _status(row) == "enabled"


def test_a_restricted_allowlist_has_no_tag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowlist = {
        **TRAEFIK["middlewares"][1],
        "ipAllowList": {"sourceRange": ["10.0.0.0/8"]},
    }
    _serve(
        monkeypatch, {**TRAEFIK, "middlewares": [TRAEFIK["middlewares"][0], allowlist]}
    )
    _, warnings = _cells(
        _get(client, "middlewares"), "ingress-middlewares", "admin-ipallowlist"
    )
    assert warnings == []


def test_a_disabled_open_router_says_both(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = {**TRAEFIK["routers"][2], "status": "disabled"}
    _serve(monkeypatch, {**TRAEFIK, "routers": [*TRAEFIK["routers"][:2], api]})
    row, warnings = _cells(_get(client, "routers"), "ingress-routers", "api")
    assert _status(row) == "disabled" and [text(w) for w in warnings] == ["no auth"]


def test_the_flow_marks_a_middleware_that_does_nothing(client: TestClient) -> None:
    flow = one(_get(client), "[data-flow='webserver-admin']")
    step = [s for s in select(flow, "[data-step]") if "admin-ipallowlist" in text(s)][0]
    assert step.get("data-tone") == "warn"
    assert "allows all" in text(step)
