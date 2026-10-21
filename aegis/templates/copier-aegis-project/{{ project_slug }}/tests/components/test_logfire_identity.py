"""Each process reports its traces under its own name, in the stack's
namespace (``logfire_tracing.configure_logfire``): the webserver, the
worker and the scheduler of one stack are told apart and kept together."""

import os
from typing import Any

import logfire
import pytest

from app.components.backend.middleware import logfire_tracing
from app.core.config import settings


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What ``logfire.configure`` was called with; the instrumentations
    it goes on to install, no-ops."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(settings, "LOGFIRE_TOKEN", "test-token")
    monkeypatch.setattr(logfire_tracing, "_configured", None)
    monkeypatch.setattr(logfire, "configure", lambda **kw: seen.update(kw))
    for name in dir(logfire):
        if name.startswith("instrument_"):
            monkeypatch.setattr(logfire, name, lambda *a, **kw: None)
    monkeypatch.setattr(
        logfire_tracing,
        "_harden_pydantic_ai_result_serializer",
        lambda: None,
        raising=False,
    )
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    return seen


@pytest.mark.parametrize("unit", ["webserver", "worker", "scheduler"])
def test_a_process_reports_its_own_name_in_the_stacks_namespace(
    configured: dict[str, Any], unit: str
) -> None:
    assert logfire_tracing.configure_logfire(unit)
    assert configured["service_name"] == unit
    assert configured["service_version"] == settings.BUILD_ID
    assert configured["environment"] == settings.APP_ENV
    attributes = os.environ["OTEL_RESOURCE_ATTRIBUTES"]
    assert f"service.namespace={settings.PROJECT_NAME}" in attributes
