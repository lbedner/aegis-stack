"""The ASGI server is swappable at run time.

``make serve ENGINE=granian`` flips one setting; both the reload and the
production path have to honor it, or a developer gets granian in dev and
uvicorn in prod without being told.
"""

from pathlib import Path
from typing import Any

import granian
import pytest

from app.core import loops
from app.core.config import settings
from app.entrypoints import webserver


@pytest.fixture
def granian_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record what the granian server would have been constructed with."""
    calls: list[dict[str, Any]] = []

    class _Recorder:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

        def serve(self) -> None:
            return None

    monkeypatch.setattr(settings, "WEBSERVER_ENGINE", "granian")
    # The entrypoint imports granian lazily, so patch it at the source.
    monkeypatch.setattr(granian, "Granian", _Recorder)
    return calls


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(webserver.uvicorn, "run", lambda *a, **kw: calls.append(kw))
    return calls


class TestEngineSelection:
    def test_uvicorn_is_the_default(
        self, uvicorn_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)

        webserver.main()

        assert len(uvicorn_calls) == 1

    def test_granian_serves_the_same_app(
        self,
        granian_calls: list[dict[str, Any]],
        uvicorn_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)

        webserver.main()

        assert not uvicorn_calls
        assert granian_calls[0]["target"] == (
            "app.integrations.main:create_integrated_app"
        )
        assert granian_calls[0]["factory"] is True
        # Granian speaks its own RSGI protocol by default; the app is ASGI.
        assert granian_calls[0]["interface"] == "asgi"
        assert granian_calls[0]["port"] == settings.PORT

    def test_granian_honors_auto_reload_scoped_to_the_app_package(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same constraint the uvicorn path is under: watching the whole
        # working directory means watching the dev bind mount.
        monkeypatch.setattr(settings, "AUTO_RELOAD", True)

        webserver.main()

        assert granian_calls[0]["reload"] is True
        assert [Path(d).name for d in granian_calls[0]["reload_paths"]] == ["app"]

    def test_an_unknown_engine_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_ENGINE", "hypercorn")

        with pytest.raises(ValueError, match="hypercorn"):
            webserver.main()


class TestLoopSelection:
    """The loop is pinned, never left to an engine's own `auto`."""

    def test_auto_never_resolves_to_rloop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Granian's own `auto` prefers rloop the moment it is importable,
        # which would move a deployment onto an alpha loop with no code
        # change. Ours prefers uvloop no matter what else is installed.
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "auto")
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())

        assert loops.resolve_loop() == "uvloop"

    def test_auto_falls_back_to_asyncio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "auto")
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: None)

        assert loops.resolve_loop() == "asyncio"

    def test_an_explicit_choice_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "rloop")

        assert loops.resolve_loop() == "rloop"

    def test_uvicorn_refuses_a_loop_it_cannot_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # rloop is valid for granian and not for uvicorn. Failing here
        # beats uvicorn failing later with its own vocabulary.
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "rloop")

        with pytest.raises(ValueError, match="uvicorn cannot run on 'rloop'"):
            webserver.uvicorn_settings()

    def test_the_matrix_says_what_each_engine_takes(self) -> None:
        # One definition, because the entrypoint enforces it and the
        # benchmark skips incompatible combinations by reading it.
        assert "rloop" in loops.ENGINE_LOOPS["granian"]
        assert "rloop" not in loops.ENGINE_LOOPS["uvicorn"]
        # zuvloop reaches neither engine through this path today.
        assert not any("zuvloop" in v for v in loops.ENGINE_LOOPS.values())

    def test_granian_is_given_the_resolved_loop(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "rloop")
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)

        webserver.main()

        assert granian_calls[0]["loop"] == "rloop"
