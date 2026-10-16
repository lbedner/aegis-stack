"""Overseer's reads as tools: what is wrong now (``health``), what broke
(``errors``) and what led up to it (``logs``), for an agent or an MCP
client."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.core.ontology.model import (
    ChangeNode,
    Edge,
    EdgeKind,
    Kind,
    ObjectNode,
    PartNode,
    RouteNode,
    SystemModel,
)
from app.core.parts import Category
from app.core.tools import acting_as, get_tool
from app.services.system import health as health_module
from app.services.system import live_status, tools, ui_errors, ui_logs
from app.services.system.errors.models import ErrorIssue
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    SystemStatus,
)
from tests._ontology import model_of

UNHEALTHY = ComponentStatusType.UNHEALTHY
# What the registry holds in the webserver, and in any other process.
HERE = {"components": ("worker",), "services": ()}
NONE: dict[str, tuple[str, ...]] = {"components": (), "services": ()}


def _status() -> SystemStatus:
    worker = ComponentStatus(
        name="worker",
        status=UNHEALTHY,
        message="1 queue stuck",
        metadata={"queues": {"system": {"queued": 40}}},
    )
    backend = ComponentStatus(name="backend", message="ok", metadata={"routes": 12})
    components = ComponentStatus(
        name="components",
        status=UNHEALTHY,
        message="1 unhealthy",
        sub_components={"backend": backend, "worker": worker},
    )
    aegis = ComponentStatus(
        name="aegis",
        status=UNHEALTHY,
        message="1 unhealthy",
        sub_components={"components": components},
    )
    return SystemStatus(
        components={"aegis": aegis}, overall_healthy=False, timestamp=datetime.now(UTC)
    )


@pytest.fixture
def status(monkeypatch: pytest.MonkeyPatch) -> SystemStatus:
    current = _status()

    async def fake() -> tuple[SystemStatus, str | None]:
        return current, None

    monkeypatch.setattr(live_status, "live_status", fake)
    return current


def test_the_three_are_registered_as_reads() -> None:
    for name in ("health", "errors", "logs"):
        tool = get_tool(name)
        assert tool is not None, name
        assert tool.effect == "read"
        assert tool.description, name  # Overseer > MCP's one-liner


async def test_health_is_a_tree_of_statuses_without_details(
    status: SystemStatus,
) -> None:
    result = await tools.health()

    worker = result["components"]["aegis"]["parts"]["components"]["parts"]["worker"]
    assert worker == {"status": "unhealthy", "message": "1 queue stuck"}
    assert result["healthy"] is False
    assert "queues" not in json.dumps(result)


async def test_health_counts_each_check_once_and_names_each_issue(
    status: SystemStatus,
) -> None:
    """A part passing on its parts' issues (``aegis``, ``components``) is
    not one more: the counts are the checks', and every check that is not
    healthy is named, with its message."""
    result = await tools.health()

    assert result["counts"] == {"healthy": 1, "unhealthy": 1}
    assert result["attention"] == [
        {
            "name": "aegis.components.worker",
            "status": "unhealthy",
            "message": "1 queue stuck",
        }
    ]


async def test_health_of_one_component_carries_its_details(
    status: SystemStatus,
) -> None:
    result = await tools.health("worker")

    assert result["component"]["metadata"]["queues"]["system"]["queued"] == 40


async def test_health_of_an_unknown_component_names_the_known_ones(
    status: SystemStatus,
) -> None:
    with pytest.raises(ValueError, match="worker"):
        await tools.health("nope")


async def test_live_status_walks_here_where_the_checks_are_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def walk(force_refresh: bool = False) -> SystemStatus:
        return _status()

    async def no_http(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the webserver walks its own checks")

    monkeypatch.setattr(health_module, "registered_health_names", lambda: HERE)
    monkeypatch.setattr(health_module, "get_system_status", walk)
    monkeypatch.setattr(httpx.AsyncClient, "get", no_http)

    status, note = await live_status.live_status()

    assert note is None
    assert not status.overall_healthy


async def test_live_status_asks_the_webserver_from_any_other_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "healthy": False,
        "status": "unhealthy",
        "service": "demo",
        "version": "1",
        "components": _status().model_dump(mode="json")["components"],
        "system_info": {},
        "timestamp": datetime.now(UTC).isoformat(),
        "healthy_components": [],
        "unhealthy_components": ["worker"],
        "health_percentage": 0.0,
    }

    async def get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        assert url.endswith("/health/detailed")
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(health_module, "registered_health_names", lambda: NONE)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    status, note = await live_status.live_status()

    assert note is None
    worker = status.components["aegis"].sub_components["components"]
    assert worker.sub_components["worker"].status == UNHEALTHY


async def test_live_status_says_when_it_only_sees_this_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def down(self: httpx.AsyncClient, url: str, **kwargs: Any) -> None:
        raise httpx.ConnectError("refused")

    async def walk(force_refresh: bool = False) -> SystemStatus:
        return _status()

    monkeypatch.setattr(health_module, "registered_health_names", lambda: NONE)
    monkeypatch.setattr(httpx.AsyncClient, "get", down)
    monkeypatch.setattr(health_module, "get_system_status", walk)

    status, note = await live_status.live_status()

    assert note is not None
    assert status.components


async def test_live_status_falls_back_on_an_answer_that_is_not_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Something else on the port, or an older build: not a crash."""

    async def other(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", url))

    async def walk(force_refresh: bool = False) -> SystemStatus:
        return _status()

    monkeypatch.setattr(health_module, "registered_health_names", lambda: NONE)
    monkeypatch.setattr(httpx.AsyncClient, "get", other)
    monkeypatch.setattr(health_module, "get_system_status", walk)

    _, note = await live_status.live_status()

    assert note == live_status.PARTIAL


def _issue() -> ErrorIssue:
    now = datetime.now(UTC)
    return ErrorIssue(
        fingerprint="abc",
        page="worker",
        service="worker",
        message="boom",
        exception_type="KeyError",
        count=3,
        first_seen=now,
        last_seen=now,
        latest_id="abc:1",
    )


async def test_errors_passes_its_filters_as_the_errors_page_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def load(query: Mapping[str, str], part: Any = None) -> dict[str, Any]:
        seen.update(query)
        return ui_errors.DEFAULTS | {"error_rows": [_issue()], "error_total": 1}

    monkeypatch.setattr(ui_errors, "load", load)

    result = await tools.errors(
        text="boom", service="worker", level="error", window_seconds=3600
    )

    assert seen == {
        "q": "boom",
        "service": "worker",
        "level": "error",
        "window": "3600",
    }
    assert result["total"] == 1
    assert result["issues"][0]["exception_type"] == "KeyError"
    json.dumps(result)


async def test_errors_of_one_issue_reads_its_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts: list[Any] = []

    async def load(query: Mapping[str, str], part: Any = None) -> dict[str, Any]:
        parts.append((dict(query), part))
        return ui_errors.DEFAULTS

    monkeypatch.setattr(ui_errors, "load", load)

    await tools.errors(issue="abc")

    assert parts == [({"issue": "abc"}, ui_errors.load_detail)]


async def test_errors_says_why_it_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    async def load(query: Mapping[str, str], part: Any = None) -> dict[str, Any]:
        return ui_errors.empty("disabled", "Error tracking needs the Redis component.")

    monkeypatch.setattr(ui_errors, "load", load)

    result = await tools.errors()

    assert result["note"] == "Error tracking needs the Redis component."


def _line(level: str, message: str) -> dict[str, Any]:
    return {
        "at": "10:00:00",
        "page": "worker",
        "instance": "my-app-worker-1",
        "level": level,
        "message": message,
        "trace": None,
        "color": 3,
        "copy_text": message,
    }


@pytest.fixture
def recent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], Any]]:
    calls: list[tuple[list[str], Any]] = []

    async def fake(pages: Sequence[str], query: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((list(pages), query))
        lines = [_line("error", f"line {i}") for i in range(5)]
        return {"lines": lines, "volume": [], "note": None}

    monkeypatch.setattr(ui_logs, "recent", fake)
    return calls


async def test_logs_reads_one_service_from_a_level_up(
    recent: list[tuple[list[str], Any]],
) -> None:
    await tools.logs(service="worker", level="error", text="boom", window_seconds=3600)

    pages, query = recent[0]
    assert pages == ["worker"]
    assert query.getlist("level") == ["error", "critical"]
    assert query.get("q") == "boom"
    assert query.get("window") == "3600"


async def test_logs_reads_every_service_by_default(
    recent: list[tuple[list[str], Any]],
) -> None:
    await tools.logs()

    pages, query = recent[0]
    assert set(pages) == set(tools.runtime.PAGES)
    assert query.getlist("level") == []


async def test_logs_keeps_what_a_reader_needs_up_to_the_limit(
    recent: list[tuple[list[str], Any]],
) -> None:
    result = await tools.logs(limit=2)

    assert len(result["lines"]) == 2
    assert set(result["lines"][0]) == {
        "at",
        "service",
        "container",
        "level",
        "message",
        "trace",
    }


async def test_logs_of_an_unknown_service_names_the_known_ones(
    recent: list[tuple[list[str], Any]],
) -> None:
    with pytest.raises(ValueError, match="worker"):
        await tools.logs(service="nope")


# ---------------------------------------------------------------------------
# ontology: what the app is (``app.core.ontology``), in small pieces
# ---------------------------------------------------------------------------


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> SystemModel:
    """A payment service whose route reaches the database through it, and
    many routes besides, as ``current`` answers."""
    parts = [
        PartNode(kind=Kind.COMPONENT, name="backend", category=Category.COMPUTE),
        PartNode(kind=Kind.COMPONENT, name="database", category=Category.DATA),
        PartNode(kind=Kind.SERVICE, name="payment", category=Category.APP),
    ]
    routes = [
        RouteNode(
            name=f"GET /api/v1/r{i}",
            method="GET",
            path=f"/r{i}",
            owner="component:backend",
        )
        for i in range(150)
    ]
    charge = RouteNode(
        name="POST /api/v1/charge",
        method="POST",
        path="/charge",
        owner="service:payment",
    )
    edges = [
        Edge(
            source="service:payment", target="component:database", kind=EdgeKind.CALLS
        ),
        Edge(
            source="component:backend",
            target="component:database",
            kind=EdgeKind.DEPENDS_ON,
        ),
        Edge(source="service:payment", target=charge.id, kind=EdgeKind.CONTAINS),
    ]
    table = ObjectNode(
        name="payment_charge",
        class_name="Charge",
        owner="service:payment",
        module="app.services.payment.models",
    )
    customer = ObjectNode(
        name="payment_customer", class_name="Customer", owner="service:payment"
    )
    refund = ChangeNode(
        name="payment.refund",
        title="Refund a charge",
        object=table.id,
        owner="service:payment",
    )
    edges += [
        Edge(
            source=table.id, target=customer.id, kind=EdgeKind.LINK, via="customer_id"
        ),
        Edge(source=refund.id, target=table.id, kind=EdgeKind.CHANGES),
    ]
    found = model_of([*parts, *routes, charge, table, customer, refund], edges)
    monkeypatch.setattr("app.core.ontology.system.current", lambda: found)
    # Read as an admin unless a test binds otherwise: sign-in off.
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    return found


@pytest.mark.usefixtures("model")
async def test_the_ontology_summary_fits_one_call_record() -> None:
    """The app, counts by kind, every part, and the app's data (its tables
    by owner with what each links to, and the changes to them): whole under
    the MCP call record's cap, so nothing a reader saw is clipped."""
    cap = pytest.importorskip("app.components.mcp.server").TEXT_CAP
    result = await tools.ontology()

    assert result["app"]["name"] == "app" and "stack" not in result
    assert result["counts"]["route"] == 151
    assert {p["id"] for p in result["parts"]} == {
        "component:backend",
        "component:database",
        "service:payment",
    }
    assert result["tables"] == {
        "service:payment": {
            "payment_charge": ["payment_customer"],
            "payment_customer": [],
        }
    }
    assert result["changes"] == {
        "payment.refund": {"title": "Refund a charge", "table": "payment_charge"}
    }
    assert len(json.dumps(result)) < cap


@pytest.mark.usefixtures("model")
async def test_a_filter_lists_the_first_hundred_and_says_how_many() -> None:
    result = await tools.ontology(kind="route")

    assert len(result["nodes"]) == 100
    assert result["total"] == 151


@pytest.mark.usefixtures("model")
async def test_a_node_comes_with_its_edges_and_neighbours() -> None:
    result = await tools.ontology(node="service:payment")

    assert result["node"]["name"] == "payment"
    assert {n["id"] for n in result["neighbors"]} >= {
        "component:database",
        "route:POST /api/v1/charge",
    }
    assert {e["kind"] for e in result["edges"]} >= {"calls", "contains"}
    ids = [n["id"] for n in result["neighbors"]]
    assert ids == sorted(ids)  # the same answer every call


@pytest.mark.usefixtures("model")
async def test_the_path_between_two_nodes_names_each_edge() -> None:
    """Where does the charge route touch the database? Through Payment."""
    result = await tools.ontology(
        node="route:POST /api/v1/charge", to="component:database"
    )

    (path,) = result["paths"]
    assert [step["kind"] for step in path] == ["contains", "calls"]
    assert path[0]["source"] == "service:payment"


@pytest.mark.usefixtures("model")
async def test_an_unknown_node_names_the_close_ones() -> None:
    with pytest.raises(ValueError, match="service:payment"):
        await tools.ontology(node="service:paymnt")


def test_the_ontology_is_a_read_any_granted_agent_may_use() -> None:
    tool = get_tool("ontology")
    assert tool is not None and tool.effect == "read" and not tool.admin


@pytest.mark.usefixtures("model")
async def test_anyone_but_an_admin_reads_only_the_apps_data() -> None:
    """The tables and the changes to them are anyone's to ask about; the
    routes, containers and providers behind them an admin's."""
    with acting_as(None, "assistant", admin=False):
        summary = await tools.ontology()
        routes = await tools.ontology(kind="route")
        table = await tools.ontology(node="object:payment_charge")
    assert summary["counts"] == {"object": 2, "change": 1}
    assert "parts" not in summary
    assert summary["tables"]["service:payment"]["payment_charge"] == [
        "payment_customer"
    ]
    assert list(summary["changes"]) == ["payment.refund"]
    assert routes["total"] == 0
    assert table["node"]["class_name"] == "Charge"
    assert table["node"]["module"] is None  # where the code lives: an admin's
    with acting_as(None, "assistant", admin=False), pytest.raises(ValueError):
        await tools.ontology(node="service:payment")

    with acting_as(None, "assistant", admin=True):
        assert (await tools.ontology(kind="route"))["total"] == 151


async def test_a_routes_dry_path_is_an_admins(app: object) -> None:
    """Every hop it can take, each at its line: the code's, so an admin's."""
    with acting_as(None, "assistant", admin=True):
        result = await tools.ontology(route="GET /health/detailed")
    hops = result["dry_path"]["hops"]
    assert hops[0]["kind"] == "handler" and hops[0]["path"].startswith("app/")
    with acting_as(None, "assistant", admin=False), pytest.raises(ValueError):
        await tools.ontology(route="GET /health/detailed")
    with acting_as(None, "assistant", admin=True), pytest.raises(ValueError):
        await tools.ontology(route="GET /nowhere")


async def test_a_routes_dry_path_is_hidden_with_the_code(
    app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside dev the source is off until an admin turns it on: the dry
    path is its lines, so an admin's token does not get them either."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    if hasattr(settings, "OVERSEER_CODE_ENABLED"):  # a stack with the Overseer
        monkeypatch.setattr(settings, "OVERSEER_CODE_ENABLED", False)
    with acting_as(None, "assistant", admin=True), pytest.raises(ValueError):
        await tools.ontology(route="GET /health/detailed")
