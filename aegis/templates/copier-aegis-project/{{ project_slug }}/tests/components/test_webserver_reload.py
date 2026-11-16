"""Dev auto-reload: uvicorn's reload supervisor, watching the app package
only, which also starts a new webserver process when the one it ran died.

Unscoped, uvicorn watches the whole working directory; in the dev
container that is the bind mount, which includes the host's ``.venv``.
A ``uv sync`` on the host then rewrites thousands of files and the
webserver restarts in a storm. The scheduler and worker already watch
``/code/app``; the webserver must match.

Uvicorn's supervisor restarts the webserver process only on a change. One
killed (out of memory) left it holding the port with nothing serving it:
every request hung, and the container, its main process alive, was never
restarted.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from uvicorn.supervisors import ChangeReload

from app.core.config import settings
from app.entrypoints import webserver


def test_reload_is_scoped_to_the_app_package(monkeypatch: pytest.MonkeyPatch) -> None:
    configs: list[Any] = []

    class Supervisor:
        def __init__(self, config: Any, target: Any, sockets: Any) -> None:
            configs.append(config)

        def run(self) -> None:
            return None

    monkeypatch.setattr(webserver, "Respawning", Supervisor)
    monkeypatch.setattr(webserver.uvicorn.Config, "bind_socket", lambda self: None)
    monkeypatch.setattr(settings, "AUTO_RELOAD", True)

    webserver.main()

    assert configs and configs[0].reload is True
    assert [Path(d).name for d in configs[0].reload_dirs] == ["app"]


@pytest.mark.parametrize(
    ("exitcode", "replaced"),
    [
        (-9, True),  # killed (out of memory): a new one, now
        (None, False),  # still serving
        # It exited itself (code that fails to import, a startup that
        # fails): a new one would fail the same, in a loop. It waits for
        # the change that fixes it, as before.
        (3, False),
    ],
)
def test_a_killed_webserver_process_is_replaced(
    monkeypatch: pytest.MonkeyPatch, exitcode: int | None, replaced: bool
) -> None:
    supervisor = webserver.Respawning.__new__(webserver.Respawning)
    supervisor.process = SimpleNamespace(exitcode=exitcode)
    restarted: list[bool] = []
    monkeypatch.setattr(supervisor, "restart", lambda: restarted.append(True))
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: None)

    assert supervisor.should_restart() is None  # no change: nothing to log
    assert restarted == ([True] if replaced else [])
