"""In a container, each role's program runs directly, not under ``uv run``.

The image is synced at build time, yet every app container started as
``uv run entrypoint.sh`` wrapping ``uv run <program>``: two idle ``uv``
processes per container, a lock check each on every start, and - for the
webserver, whose branch had no ``exec`` - a bash in between, so ``docker
stop`` killed it by signal (exit 143) before its shutdown hooks ran.

These run the rendered entrypoint under bash with stub commands on PATH that
record who called them and from which process: the program a role ends up
running must be the entrypoint's own process (``exec``), and ``uv`` may run
only as the one-off dev ``uv sync``, never as a resident parent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from tests.core._compose import entrypoint_calls as _run

SLUG = "{{ project_slug }}"


def _render(rel: str, **overrides: Any) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    ctx = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    return env.get_template(f"{SLUG}/{rel}").render(ctx)


ROLES = [
    pytest.param(["webserver"], {}, "python", id="webserver"),
    pytest.param(["scheduler"], {"include_scheduler": True}, "python", id="scheduler"),
    pytest.param(
        ["worker", "system"],
        {"include_worker": True, "worker_backend": "arq"},
        "python",
        id="worker-arq",
    ),
    pytest.param(
        ["worker", "system"],
        {"include_worker": True, "worker_backend": "taskiq"},
        "taskiq",
        id="worker-taskiq",
    ),
    pytest.param(
        ["worker", "system"],
        {"include_worker": True, "worker_backend": "dramatiq"},
        "dramatiq",
        id="worker-dramatiq",
    ),
]


@pytest.mark.parametrize(("role", "ctx", "program"), ROLES)
def test_production_execs_the_program_and_never_runs_uv(
    tmp_path: Path, role: list[str], ctx: dict[str, Any], program: str
) -> None:
    calls = _run(tmp_path, role, {}, **ctx)

    assert not [c for c in calls if c["cmd"] == "uv"], calls
    assert calls[-1]["cmd"] == program
    assert calls[-1]["exec"], "the program must replace the entrypoint (exec)"


@pytest.mark.parametrize(("role", "ctx", "program"), ROLES)
def test_dev_syncs_once_then_execs_the_program(
    tmp_path: Path, role: list[str], ctx: dict[str, Any], program: str
) -> None:
    """``uv add`` on the host still lands on restart: one ``uv sync``, which
    exits, then the program (under its reloader) replaces the entrypoint."""
    calls = _run(tmp_path, role, {"APP_ENV": "dev"}, **ctx)

    uv = [c for c in calls if c["cmd"] == "uv"]
    assert [c["args"].split()[0] for c in uv] == ["sync"], calls
    assert not uv[0]["exec"]
    assert calls[-1]["cmd"] in (program, "python")  # python: the dev supervisor
    assert calls[-1]["exec"]


def test_the_image_runs_the_entrypoint_directly() -> None:
    dockerfile = (get_template_path() / SLUG / "Dockerfile.jinja").read_text()
    entrypoint = next(
        line for line in dockerfile.splitlines() if line.startswith("ENTRYPOINT")
    )
    assert json.loads(entrypoint.removeprefix("ENTRYPOINT").strip())[0] != "uv"


def test_every_app_container_has_an_init() -> None:
    """Whatever is PID 1 must reap the orphans granian, taskiq and dramatiq
    leave behind, and pass signals on; the program itself does neither."""
    compose = yaml.safe_load(
        _render(
            "docker-compose.yml.jinja",
            include_worker=True,
            include_scheduler=True,
            include_redis=True,
        )
    )
    assert compose["x-app"].get("init") is True
