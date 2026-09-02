"""Every long-running process in dev reloads when its code changes.

The webserver reloads, so a stale worker is invisible: the dashboard shows
the fix landing while the worker keeps executing whatever it imported at
boot. That gap has cost real debugging time, so it is pinned here per
backend rather than left to whichever branch someone last touched.
"""

from __future__ import annotations

from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
ENTRYPOINT = "scripts/entrypoint.sh.jinja"
# The reloaders each backend can be run under: watchfiles wraps a command,
# arq and dramatiq watch a directory themselves.
RELOADERS = ("watchfiles", "--watch")


def _render(context: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{ENTRYPOINT}").render(context)


def _ctx(**overrides: Any) -> dict[str, Any]:
    return {**get_copier_defaults(), "include_worker": True, **overrides}


def _worker_branch(rendered: str) -> str:
    start = rendered.index('"$run_command" = "worker"')
    end = rendered.index('elif [ "$run_command"', start + 1)
    return rendered[start:end]


@pytest.mark.parametrize("backend", ["arq", "dramatiq", "taskiq"])
def test_the_worker_reloads_in_dev(backend: str) -> None:
    branch = _worker_branch(_render(_ctx(worker_backend=backend)))

    assert any(flag in branch for flag in RELOADERS), (
        f"the {backend} worker has no reloader in dev:\n{branch}"
    )
    assert "WORKER_WATCH" in branch, f"the {backend} worker cannot be told to watch"


def test_the_scheduler_reloads_in_dev() -> None:
    rendered = _render(_ctx(include_scheduler=True))
    start = rendered.index('"$run_command" = "scheduler"')
    end = rendered.index('elif [ "$run_command"', start + 1)

    assert "watchfiles" in rendered[start:end]
