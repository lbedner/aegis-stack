"""`make serve ENGINE=granian` reaches the container.

Make exports command-line variables to its recipes, so ``ENGINE`` arrives
in this process's environment; compose only forwards what the compose file
names, which is ``WEBSERVER_ENGINE``. The translation happens here, and a
plain ``make serve`` must not pin an engine at all.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from scripts import dev_tasks


@pytest.fixture
def serve_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What ``serve()`` hands to ``subprocess.run``."""
    captured: dict[str, Any] = {}

    def fake_run(_cmd: list[str], **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dev_tasks, "resolve_ports", lambda **_: {})
    monkeypatch.delenv("ENGINE", raising=False)
    monkeypatch.delenv("WEBSERVER_ENGINE", raising=False)
    return captured


def test_engine_becomes_the_webserver_setting(
    serve_kwargs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENGINE", "granian")

    dev_tasks.serve()

    assert serve_kwargs["env"]["WEBSERVER_ENGINE"] == "granian"


def test_plain_serve_pins_no_engine(serve_kwargs: dict[str, Any]) -> None:
    dev_tasks.serve()

    assert "WEBSERVER_ENGINE" not in serve_kwargs["env"]
