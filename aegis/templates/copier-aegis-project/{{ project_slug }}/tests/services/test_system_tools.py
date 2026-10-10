"""Overseer's reads as tools: what is wrong now (``health``), what broke
(``errors``) and what led up to it (``logs``), for an agent or an MCP
client."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
from typing import Any

import httpx
import pytest

from app.core.tools import get_tool
from app.services.system import health as health_module
from app.services.system import live_status, tools, ui_errors, ui_logs
from app.services.system.errors.models import ErrorIssue
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    SystemStatus,
)

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
