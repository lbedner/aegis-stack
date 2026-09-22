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


class TestTheArqWorkerOwnsItsLoop:
    """``python -m arq <settings>`` calls ``asyncio.get_event_loop()`` with
    no running loop, which is a RuntimeError on Python 3.14. arq's own
    ``--watch`` hid it by running the worker inside ``asyncio.run`` - so
    the dev branch worked, the non-dev branch (the one a deployment takes)
    was dead, and the "reload" re-ran the worker in the same process
    without re-importing anything. Found in aegis-steward, which hit all
    three."""

    def _branch(self) -> str:
        return _worker_branch(_render(_ctx(worker_backend="arq")))

    def test_neither_branch_runs_arqs_cli(self) -> None:
        branch = self._branch()
        assert "python -m arq" not in branch, (
            "arq's CLI cannot start its own event loop on Python 3.14"
        )

    def test_both_branches_run_the_same_entrypoint(self) -> None:
        """A command only dev runs is a command only dev has tested."""
        assert self._branch().count("app.entrypoints.worker") == 2

    def test_dev_restarts_the_process_rather_than_reconnecting(self) -> None:
        branch = self._branch()
        assert "--watch" not in branch, (
            "arq's watch flag re-runs the worker in the same process and "
            "re-imports nothing"
        )
        assert "watchfiles --filter python" in branch
