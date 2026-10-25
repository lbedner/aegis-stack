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
    QueueNode,
    RouteNode,
    SystemModel,
    TaskNode,
)
from app.core.parts import Category
from app.core.tools import acting_as, get_tool
from app.services.system import health as health_module
from app.services.system import (
    live_status,
    node_now,
    pattern_findings,
    service_parts,
    tools,
    ui_errors,
    ui_logs,
    ui_runtime,
)
from app.services.system.errors.models import ErrorIssue
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    SystemStatus,
)
from app.services.system.node_now import ContainerNow, NodeNow
from app.services.system.pattern_findings import Finding
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


async def test_health_keeps_what_fits_a_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dashboard's details are for a page: every table's schema is tens
    of thousands of tokens. An agent gets the rest, and the names of what
    was left out; a URL's password is hidden in every check already."""
    database = ComponentStatus(
        name="database",
        message="ok",
        metadata={
            "implementation": "postgresql",
            "url": "postgresql://app:secret@db:5432/app",
            "table_count": 50,
            "table_schemas": [
                {"name": f"t{i}", "columns": list("abcdefgh")} for i in range(50)
            ],
        },
    )
    current = SystemStatus(
        components={"database": database},
        overall_healthy=True,
        timestamp=datetime.now(UTC),
    )

    async def fake() -> tuple[SystemStatus, str | None]:
        return current, None

    monkeypatch.setattr(live_status, "live_status", fake)
    told = (await tools.health("database"))["component"]["metadata"]
    assert told["implementation"] == "postgresql" and told["table_count"] == 50
    assert "secret" not in json.dumps(told)
    assert told["url"] == "postgresql://app:***@db:5432/app"
    assert told["omitted"] == ["table_schemas"]


async def test_a_few_short_rows_fit_where_a_schema_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduler's jobs, each with when it runs next, are what she is
    asked for (2026-10-24: "when they run next" was left out)."""
    jobs = [
        {
            "job_id": f"job_{i}",
            "name": f"Job number {i}",
            "next_run": "2026-10-24T19:00:00",
            "schedule": "Every 1h",
            "function": "app.components.scheduler.main:scheduled_run",
            "description": "One run of a scheduled job: its task enqueued",
        }
        for i in range(6)
    ]
    scheduler = ComponentStatus(
        name="scheduler", message="ok", metadata={"upcoming_tasks": jobs}
    )
    current = SystemStatus(
        components={"scheduler": scheduler},
        overall_healthy=True,
        timestamp=datetime.now(UTC),
    )

    async def fake() -> tuple[SystemStatus, str | None]:
        return current, None

    monkeypatch.setattr(live_status, "live_status", fake)
    told = (await tools.health("scheduler"))["component"]["metadata"]
    assert [job["next_run"] for job in told["upcoming_tasks"]] == [
        "2026-10-24T19:00:00"
    ] * 6


@pytest.mark.usefixtures("status")
async def test_health_of_a_part_takes_its_ontology_id() -> None:
    """She holds the ontology's ids (``component:worker``): the check is
    the same part's."""
    result = await tools.health(component="component:worker")
    assert result["component"]["name"] == "worker"


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


@pytest.fixture
def errors_asked(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """One issue for any query; the query the store was asked."""
    asked: dict[str, Any] = {}

    async def load(query: Mapping[str, str], part: Any = None) -> dict[str, Any]:
        asked.update(query)
        return ui_errors.DEFAULTS | {"error_rows": [_issue()], "error_total": 1}

    monkeypatch.setattr(ui_errors, "load", load)
    return asked


async def test_errors_passes_its_filters_as_the_errors_page_query(
    errors_asked: dict[str, Any],
) -> None:
    seen = errors_asked
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
        "logger": None,
        "fields": [],
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
        "logger",
        "fields",
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

    # Traffic other tests sent in this process is not this model's.
    async def nothing_seen() -> dict[Any, Any]:
        return {}

    monkeypatch.setattr("app.core.edges.observed", nothing_seen)
    # The parts report is built once a process: never from this model.
    monkeypatch.setattr(service_parts, "report", lambda: None)
    monkeypatch.setattr(pattern_findings, "findings", lambda report: [])
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


async def test_a_queue_has_its_own_health_and_a_part_named_like_it_does_not(
    model: SystemModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load test queue's check sits under the worker's queues; read by
    name anywhere in the tree it was the load test service's (2026-10-25),
    from the node and from the health tool alike."""
    queue = QueueNode(name="load_test", owner="component:backend")
    shared = PartNode(kind=Kind.SHARED, name="load_test", category=Category.STACK)
    found = model_of([*model.nodes, queue, shared], model.edges)
    monkeypatch.setattr("app.core.ontology.system.current", lambda: found)
    checked = ComponentStatus(name="load_test", message="idle")
    tree = checked
    for name in ("queues", "worker", "components"):
        tree = ComponentStatus(
            name=name, message="ok", sub_components={tree.name: tree}
        )
    # A check of the same name met first, by a search of the whole tree.
    other = ComponentStatus(name="load_test", message="a service's")
    services = ComponentStatus(
        name="services", message="ok", sub_components={"load_test": other}
    )
    aegis = ComponentStatus(
        name="aegis",
        message="ok",
        sub_components={"services": services, "components": tree},
    )
    status = SystemStatus(
        components={"aegis": aegis}, overall_healthy=True, timestamp=datetime.now(UTC)
    )

    async def fake() -> tuple[SystemStatus, str | None]:
        return status, None

    monkeypatch.setattr(live_status, "live_status", fake)

    of_queue = await tools.ontology(node=queue.id)
    of_shared = await tools.ontology(node=shared.id)

    assert NodeNow.model_validate(of_queue["now"]).health == checked
    assert of_shared["now"]["health"]["message"] == "a service's"  # its own
    told = await tools.health(queue.id)
    assert told["component"]["message"] == "idle"


async def test_a_task_is_listed_on_its_queue(
    model: SystemModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asked what a queue runs, she reads it off the listing."""
    task = TaskNode(name="sync_catalog", queue="system", owner="component:backend")
    found = model_of([*model.nodes, task], model.edges)
    monkeypatch.setattr("app.core.ontology.system.current", lambda: found)

    result = await tools.ontology(kind="task")

    assert [(n["id"], n["queue"]) for n in result["nodes"]] == [
        ("task:sync_catalog", "system")
    ]


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
    # A call that waits is every call: only a hand-off says its mode.
    assert all("mode" not in e for e in result["edges"])


@pytest.mark.usefixtures("model")
async def test_several_nodes_are_one_call_each_answered_as_alone() -> None:
    """A part and its neighbours asked at once read as one call, not one a
    part (2026-10-23: nine calls to say how AI was wired)."""
    asked = ["service:payment", "component:database"]
    result = await tools.ontology(node=asked)

    alone = [await tools.ontology(node=n) for n in asked]
    same = ("node", "edges", "neighbors", "findings")
    assert [{k: a[k] for k in same} for a in result["nodes"]] == [
        {k: a[k] for k in same} for a in alone
    ]
    with pytest.raises(ValueError, match="one node"):
        await tools.ontology(node=asked, to="component:database")


@pytest.mark.usefixtures("status")
async def test_what_is_wrong_right_now_is_one_line() -> None:
    """The line her current message carries while something is wrong
    (2026-10-16): the system prompt keeps nothing live, so its cache
    holds."""
    now = await node_now.right_now()

    assert [a.name for a in now.attention] == ["aegis.components.worker"]
    line = now.line()
    assert line is not None and "worker" in line and "1 queue stuck" in line


async def test_health_it_could_not_read_is_not_all_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence would read as all clear: a process that sees only part of
    the checks says so, and a read that fails says so too, never failing
    the turn it rides (2026-10-16)."""
    empty = SystemStatus(
        components={}, overall_healthy=True, timestamp=datetime.now(UTC)
    )

    async def partial() -> tuple[SystemStatus, str | None]:
        return empty, live_status.PARTIAL

    async def broken() -> tuple[SystemStatus, str | None]:
        raise RuntimeError("checks down")

    for read in (partial, broken):
        monkeypatch.setattr(live_status, "live_status", read)
        assert (await node_now.right_now()).line()


async def test_an_ai_that_keeps_no_ledger_reads_no_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An AI service without a database keeps no ledger, so its facade
    offers no spend: the AI node reads none rather than raising."""
    ai = pytest.importorskip("app.services.ai.service")

    def offered(name: str) -> Any:
        raise AttributeError(name)

    monkeypatch.setattr(ai, "__all__", [n for n in ai.__all__ if n != "spend_windows"])
    monkeypatch.setattr(ai, "__getattr__", offered)
    node = PartNode(kind=Kind.SERVICE, name="ai", category=Category.APP)
    assert await node_now._spend(node) == ()


def test_nothing_wrong_says_nothing() -> None:
    assert node_now.RightNow(attention=(), read_at=datetime.now(UTC)).line() is None


@pytest.mark.usefixtures("model", "status")
async def test_a_part_says_what_is_true_of_it_now(
    errors_asked: dict[str, Any],
) -> None:
    """Its health check and the errors it owns, read when asked, as one
    model: live data she reads off the node, not out of her prompt
    (2026-10-16)."""
    asked = errors_asked
    result = await tools.ontology(node="component:backend")

    now = NodeNow.model_validate(result["now"])
    assert now.health is not None and now.health.name == "backend"
    assert asked == {"app_component": "backend"}
    assert [i.fingerprint for i in now.errors] == [_issue().fingerprint]
    assert now.errors_total == 1


@pytest.fixture
def sampled(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """One container on any page, as the sampler last read it; the pages
    asked for."""
    asked: list[str] = []

    async def sampled(page: str) -> dict[str, Any]:
        asked.append(page)
        row = {
            "name": "worker-system-1",
            "state": "running",
            "restarts_value": 0,
            "uptime_seconds": 3600,
            "cpu_value": 1.5,
            "memory_value": 200 * 1024**2,
            "memory_capacity": 1024**3,
            "memory_percent": 19.5,
        }
        return {"rows": [row], "note": None}

    monkeypatch.setattr(ui_runtime, "sampled", sampled)
    return asked


@pytest.mark.usefixtures("model", "status", "errors_asked")
async def test_a_part_says_what_each_of_its_containers_uses(
    sampled: list[str],
) -> None:
    """Each container behind it, as its Overseer page reads them: asked
    which worker was using the memory, she had only the warning's one
    line (2026-10-24)."""
    result = await tools.ontology(node="component:backend")

    now = NodeNow.model_validate(result["now"])
    assert sampled == [ui_runtime.page_of("backend")]
    (box,) = now.containers
    assert (box.name, box.state, box.restarts) == ("worker-system-1", "running", 0)
    assert (box.memory_mb, box.memory_limit_mb, box.memory_percent) == (200, 1024, 19.5)
    assert box.cpu_percent == 1.5


@pytest.mark.usefixtures("status")
async def test_health_of_a_part_says_what_its_containers_use(
    sampled: list[str],
) -> None:
    """Asked what is happening on a worker, she reaches for health: it
    carries the same containers as the part's ontology answer."""
    result = await tools.health(component="component:worker")

    assert sampled == [ui_runtime.page_of("worker")]
    (box,) = [ContainerNow.model_validate(c) for c in result["containers"]]
    assert (box.memory_mb, box.memory_limit_mb) == (200, 1024)


@pytest.mark.usefixtures("model", "status")
async def test_a_table_has_no_now() -> None:
    """What is live is a part's: a table is what its code says."""
    result = await tools.ontology(node="object:payment_charge")

    assert result["now"] is None


def _finding(subject: str) -> Finding:
    return Finding(
        check="parts.through-facade",
        subject=subject,
        severity="warn",
        title="Other services through their facade",
        why="It depends on how the other is organised.",
        evidence=("app/services/payment/service.py:3",),
        action="Call it through its service.py.",
        fingerprint=subject,
    )


@pytest.fixture
def found(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the parts pattern finds: one about payment, one about blog."""
    monkeypatch.setattr(
        pattern_findings,
        "findings",
        lambda report: [_finding("service:payment"), _finding("service:blog")],
    )


@pytest.mark.usefixtures("model", "status", "found", "errors_asked")
async def test_a_part_says_what_its_code_breaks() -> None:
    """The findings the map shows on a part, on its node: what she reads to
    say how it is built, not only how it is doing."""
    result = await tools.ontology(node="service:payment")

    findings = [Finding.model_validate(f) for f in result["findings"]]
    assert [f.subject for f in findings] == ["service:payment"]
    assert findings[0].evidence == ("app/services/payment/service.py:3",)


@pytest.mark.usefixtures("model", "status", "found")
async def test_a_table_has_no_findings() -> None:
    result = await tools.ontology(node="object:payment_charge")

    assert result["findings"] == []


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
