"""The health report as the terminal draws it, and what it reads."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.cli import health, health_display
from app.cli.health_messages import _translate_health_msg
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    DetailedHealthResponse,
)


def _part(
    name: str,
    status: ComponentStatusType = ComponentStatusType.HEALTHY,
    **subs: ComponentStatus,
) -> ComponentStatus:
    return ComponentStatus(
        name=name, status=status, message=f"{name} says", sub_components=subs
    )


def _response(status: str, **fields: Any) -> DetailedHealthResponse:
    return DetailedHealthResponse(
        **{
            "healthy": status == "healthy",
            "status": status,
            "service": "app",
            "version": "0.1.0",
            "components": {"aegis": _part("aegis")},
            "system_info": {},
            "timestamp": "2026-11-05T00:00:00+00:00",
            "healthy_components": [],
            "unhealthy_components": [],
            "health_percentage": 100.0,
            **fields,
        }
    )


def _report(response: DetailedHealthResponse, detailed: bool = True) -> str:
    with health_display.console.capture() as captured:
        health_display._display_health_status(response, detailed)
    return captured.get()


@pytest.mark.parametrize(
    ("status", "says", "never"),
    [
        ("healthy", "Healthy", "Unhealthy"),
        ("warning", "Warning", "Unhealthy"),
        ("info", "Info", "Unhealthy"),
        ("unhealthy", "Unhealthy", "Warning"),
    ],
)
def test_the_overall_line_says_the_status_the_api_sent(
    status: str, says: str, never: str
) -> None:
    head = _report(_response(status)).split("Timestamp")[0]
    assert f"Overall Status: {says}" in head
    assert never not in head


def test_labels_take_their_colon_from_the_locale() -> None:
    shown = _report(_response("healthy", system_info={"python_version": "3.13.1"}))
    assert ": 3.13.1" in shown
    assert "：" not in shown
    assert (
        _translate_health_msg("Load testing and performance testing: 10 processing")
        == "Load testing and performance testing: 10 processing"
    )


def test_tree_guides_hold_under_a_warning_parent() -> None:
    warning = ComponentStatusType.WARNING
    backend = _part("backend", warning, memory=_part("memory", warning))
    groups = _part("components", warning, backend=backend, cache=_part("cache"))
    root = _part("aegis", warning, components=groups, services=_part("services"))
    lines = _report(_response("warning", components={"aegis": root})).splitlines()

    def line(name: str) -> str:
        return next(ln for ln in lines if f" {name} " in ln and "──" in ln)

    assert line("components").startswith("   ├── ")
    assert line("backend").startswith("   │   ├── ")
    assert line("memory").startswith("   │   │   └── ")
    assert line("cache").startswith("   │   └── ")
    assert line("services").startswith("   └── ")


@pytest.mark.asyncio
async def test_plain_status_draws_the_components_too() -> None:
    """``/health/`` is a liveness probe: its components are always empty, so
    the plain report drew "0 components" and an empty tree on a healthy stack."""
    root = _part("aegis", components=_part("components", cache=_part("cache")))
    answer = _response("healthy", components={"aegis": root})
    with patch.object(health, "get_health_data", AsyncMock(return_value=answer)):
        with health_display.console.capture() as captured:
            await health.health_status(detailed=False, json_output=False)
    assert "cache" in captured.get()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "passes"),
    [("healthy", True), ("info", True), ("warning", True), ("unhealthy", False)],
)
async def test_the_probe_fails_only_on_unhealthy(status: str, passes: bool) -> None:
    """It read ``/health/``, which answers healthy whenever the process is up."""
    answer = _response(status)
    with patch.object(health, "get_health_data", AsyncMock(return_value=answer)):
        assert await health.is_system_healthy() is passes


@pytest.mark.asyncio
async def test_the_probe_fails_when_the_api_does_not_answer() -> None:
    failed = AsyncMock(side_effect=ConnectionError("refused"))
    with patch.object(health, "get_health_data", failed):
        assert await health.is_system_healthy() is False
