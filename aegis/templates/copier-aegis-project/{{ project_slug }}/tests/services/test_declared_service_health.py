"""A service's health check is declared by the service: ``HEALTH`` in its
``health`` module, found on disk and registered at startup, so an app's own
service is on the dashboard with no edit to the framework's files."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from app.core.discovery import declared_by, modules_named
from app.core.ownership import SERVICE
from app.core.parts import PARTS
import app.services as services
from app.services.system.health import (
    register_declared_service_health,
    registered_health_names,
)

_HEALTH = "async def check() -> None: ...\nHEALTH = check\n"


def test_a_declared_check_is_registered_under_its_service(
    fake_service: Callable[..., Path],
) -> None:
    fake_service("demo_health", health=_HEALTH)
    fake_service("demo_quiet", health="")

    with patch("app.services.system.health._service_health_checks", {}):
        register_declared_service_health()
        registered = registered_health_names()["services"]

    assert "demo_health" in registered
    assert "demo_quiet" not in registered, "a health module with no HEALTH is not one"


def test_every_framework_service_with_a_check_declares_it() -> None:
    """A service the aegis CLI ships is registered only through ``HEALTH``:
    one left out would drop off the dashboard with no error. (A plugin's
    may register through its spec's ``health_checks`` instead.)"""
    declared = {owner for owner, _ in declared_by(services, "health", "HEALTH", False)}
    checked = {found.split(".")[2] for found in modules_named(services, "health")}
    shipped = {name for name, part in PARTS.items() if part.kind == SERVICE}

    assert checked & shipped <= declared, (checked & shipped) - declared
