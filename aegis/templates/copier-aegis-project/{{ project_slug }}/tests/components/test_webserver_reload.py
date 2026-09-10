"""Dev auto-reload watches the app package only.

Unscoped, uvicorn watches the whole working directory; in the dev
container that is the bind mount, which includes the host's ``.venv``.
A ``uv sync`` on the host then rewrites thousands of files and the
webserver restarts in a storm. The scheduler and worker already watch
``/code/app``; the webserver must match.
"""

from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.entrypoints import webserver


def test_reload_is_scoped_to_the_app_package(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(webserver.uvicorn, "run", lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(settings, "AUTO_RELOAD", True)

    webserver.main()

    assert calls and calls[0]["reload"] is True
    dirs = [Path(d).name for d in calls[0]["reload_dirs"]]
    assert dirs == ["app"]
