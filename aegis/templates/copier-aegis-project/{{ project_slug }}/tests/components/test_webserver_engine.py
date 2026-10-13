"""The ASGI server is swappable at run time.

``make serve ENGINE=granian`` flips one setting; both the reload and the
production path have to honor it, or a developer gets granian in dev and
uvicorn in prod without being told.
"""

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import granian
import pytest

from app.core import loops
from app.core.config import settings
from app.entrypoints import webserver


@pytest.fixture(autouse=True)
def _nothing_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    """No store to read: the engine and loop are the settings' own, unless
    a test saves one (``_saving``)."""
    monkeypatch.setattr(webserver, "apply_saved", lambda: None)


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

    def test_granian_respawns_a_dead_worker_in_dev(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Granian defaults this off, which means one transient bad save
        # stops the dev server permanently and prints no error.
        monkeypatch.setattr(settings, "AUTO_RELOAD", True)

        webserver.main()

        assert granian_calls[0]["respawn_failed_workers"] is True

    def test_granian_fails_fast_in_production(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No reloader there, and the container healthcheck already
        # restarts a dead server. Respawning would mask a crashloop.
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)

        webserver.main()

        assert granian_calls[0]["respawn_failed_workers"] is False

    def test_granian_reload_kills_a_worker_that_will_not_stop(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Granian's default waits on the old worker forever. A worker whose
        # websocket handler never returns (an open dashboard session) then
        # leaves nothing serving the port until the container is restarted.
        monkeypatch.setattr(settings, "AUTO_RELOAD", True)

        webserver.main()

        timeout = granian_calls[0]["workers_kill_timeout"]
        assert isinstance(timeout, int) and timeout > 0

    def test_granian_drains_without_a_deadline_in_production(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No reload there: a stop is a deploy, and the container runtime
        # already bounds it. Cutting in-flight requests short is its call.
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)

        webserver.main()

        assert granian_calls[0].get("workers_kill_timeout") is None

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
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())

        assert loops.resolve_loop() == "rloop"

    def test_a_pinned_loop_that_is_not_installed_is_refused_by_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # rloop is not a dependency. Passing its name through let granian's
        # worker die on it, so a bench sweep lost every result it had and
        # `make serve LOOP=rloop` failed inside granian instead of here.
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "rloop")
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: None)

        with pytest.raises(ValueError, match="rloop is not installed"):
            loops.resolve_loop()

    def test_asyncio_never_needs_installing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "asyncio")
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: None)

        assert loops.resolve_loop() == "asyncio"

    def test_uvicorn_refuses_a_loop_it_cannot_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # rloop is valid for granian and not for uvicorn. Failing here
        # beats uvicorn failing later with its own vocabulary.
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "rloop")

        with pytest.raises(ValueError, match="uvicorn cannot run on 'rloop'"):
            webserver.uvicorn_settings("rloop")

    def test_granian_refuses_a_loop_it_cannot_run(self) -> None:
        """The half that had no check at all.

        ``serve_granian`` used to hand the name straight to
        ``Loops(loop)``, so a bad pairing surfaced as granian's own enum
        lookup failing - no mention of which loops granian takes, and
        none of the sentence the uvicorn path had written for exactly
        this case.
        """
        with pytest.raises(ValueError, match="granian cannot run on 'zuvloop'"):
            loops.check_engine_loop("granian", "zuvloop")

    def test_the_refusal_names_where_the_loop_does_work(self) -> None:
        """A loop is never wrong, only wrong for this engine, so the
        error says which engine would have taken it."""
        with pytest.raises(ValueError) as caught:
            loops.check_engine_loop("uvicorn", "rloop")
        assert "granian accepts" in str(caught.value)

    def test_auto_passes_for_either_engine(self) -> None:
        """``auto`` is not a loop, it is a promise to resolve to a good
        one, so the pairing check must not reject it."""
        loops.check_engine_loop("uvicorn", "auto")
        loops.check_engine_loop("granian", "auto")

    def test_an_engine_nobody_ships_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="unknown engine 'hypercorn'"):
            loops.check_engine_loop("hypercorn", "uvloop")

    def test_the_matrix_says_what_each_engine_takes(self) -> None:
        # One definition, because the entrypoint enforces it and the
        # benchmark skips incompatible combinations by reading it.
        assert "rloop" in loops.ENGINE_LOOPS["granian"]
        assert "rloop" not in loops.ENGINE_LOOPS["uvicorn"]
        # And the mirror image: zuvloop is uvicorn's alone.
        assert "zuvloop" in loops.ENGINE_LOOPS["uvicorn"]
        assert "zuvloop" not in loops.ENGINE_LOOPS["granian"]

    def test_granian_is_given_the_resolved_loop(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "rloop")
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())

        webserver.main()

        assert granian_calls[0]["loop"] == "rloop"


def _saving(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """The Overseer has saved ``values``: applied as the entrypoint starts."""

    def apply() -> None:
        for name, value in values.items():
            monkeypatch.setattr(settings, name, value)

    monkeypatch.setattr(webserver, "apply_saved", apply)


def _applied(monkeypatch: pytest.MonkeyPatch, **saved: str) -> list[str]:
    """``saved`` read from a store by the real ``apply_saved``, as every
    process starts: the names it applied."""
    from app.core import saved_settings

    for name in ("WEBSERVER_ENGINE", "WEBSERVER_LOOP"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(saved_settings, "IN_ENV", frozenset())
    monkeypatch.setattr(saved_settings.secrets, "store_name", lambda: "database")

    async def get_many(*names: str) -> dict[str, str | None]:
        return {name: saved.get(name) for name in names}

    monkeypatch.setattr(saved_settings.secrets, "get_many", get_many)
    return asyncio.run(saved_settings.apply_saved())


class TestSavedInTheOverseer:
    """The engine and loop are settings Overseer > Settings saves: read by
    the entrypoint before it starts either, so a saved choice applies on
    the next start, and only one this environment can start is offered or
    applied."""

    def test_a_saved_engine_is_the_one_started(
        self, granian_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_ENGINE", "uvicorn")
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)
        _saving(monkeypatch, WEBSERVER_ENGINE="granian")

        webserver.main()

        assert len(granian_calls) == 1

    def test_a_saved_loop_is_checked_against_the_saved_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The engine applies first, so the loop is one it takes: rloop
        saved with granian applies; zuvloop (uvicorn's) is skipped, and
        the loop stays ``auto``. The server still starts."""
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())
        monkeypatch.setattr(loops.sys, "version_info", (3, 14, 0))

        both = _applied(monkeypatch, WEBSERVER_ENGINE="granian", WEBSERVER_LOOP="rloop")
        assert both == ["WEBSERVER_ENGINE", "WEBSERVER_LOOP"]
        assert settings.WEBSERVER_LOOP == "rloop"

        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "auto")
        one = _applied(
            monkeypatch, WEBSERVER_ENGINE="granian", WEBSERVER_LOOP="zuvloop"
        )
        assert one == ["WEBSERVER_ENGINE"]
        assert settings.WEBSERVER_LOOP == "auto"

    def test_the_loops_offered_are_the_running_engines(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())
        monkeypatch.setattr(loops.sys, "version_info", (3, 14, 0))
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)
        monkeypatch.setattr(settings, "WEBSERVER_ENGINE", "granian")
        assert loops.offered_loops() == ["auto", "asyncio", "uvloop", "rloop"]
        monkeypatch.setattr(settings, "WEBSERVER_ENGINE", "uvicorn")
        assert loops.offered_loops() == ["auto", "asyncio", "uvloop", "zuvloop"]
        # Reload is uvicorn's supervisor: nowhere to hand zuvloop a coroutine.
        monkeypatch.setattr(settings, "AUTO_RELOAD", True)
        assert "zuvloop" not in loops.offered_loops()
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: None)
        assert loops.offered_loops() == ["auto", "asyncio"]

    def test_only_an_installed_engine_is_offered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A saved engine gone from the image (granian removed) is skipped
        as it applies, rather than failing the start on its import."""
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: None)
        assert loops.offered_engines() == ["uvicorn"]
        assert _applied(monkeypatch, WEBSERVER_ENGINE="granian") == []

    def test_both_are_settings_the_overseer_saves(self) -> None:
        from app.core import saved_settings

        assert saved_settings.options("WEBSERVER_ENGINE") == ["uvicorn", "granian"]
        assert "auto" in (saved_settings.options("WEBSERVER_LOOP") or [])

    def test_the_connections_a_read_opens_are_closed_before_serving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The entrypoint reads on one event loop and serves on another:
        what the read opened (the cache's pool, the database's) is closed
        first, so serving opens its own instead of reusing dead ones."""
        from app.core import boot
        from app.core.cache import get_cache

        closed: list[str] = []

        async def nothing() -> None:
            return None

        async def close() -> None:
            closed.append("cache")

        monkeypatch.setattr(boot, "apply_saved_overrides", nothing)
        monkeypatch.setattr(get_cache(), "aclose", close)
        database = importlib.util.find_spec("app.core.db") is not None
        if database:
            from app.core import db

            class _Engine:
                async def dispose(self) -> None:
                    closed.append("database")

            monkeypatch.setattr(db, "async_engine", _Engine())

        asyncio.run(boot.apply_before_serving())

        assert closed == ["cache", "database"] if database else ["cache"]


@pytest.fixture
def on_314(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend we are on a Python that can run zuvloop, with it installed."""
    monkeypatch.setattr(loops.sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())


class TestZuvloop:
    """zuvloop is uvicorn-only, 3.14+, and needs a different startup shape.

    `uvicorn.run()` owns the event loop, so reaching a loop uvicorn does
    not know about means dropping to Config + Server with `loop="none"`
    and letting zuvloop provide one.
    """

    def test_the_matrix_offers_it_to_uvicorn_only(self) -> None:
        assert "zuvloop" in loops.ENGINE_LOOPS["uvicorn"]
        # Granian's Loops enum has no member for it, and zuvloop ships no
        # EventLoopPolicy to redirect granian's asyncio builder.
        assert "zuvloop" not in loops.ENGINE_LOOPS["granian"]

    def test_it_is_refused_below_314(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "zuvloop")
        monkeypatch.setattr(loops.sys, "version_info", (3, 13, 9))

        with pytest.raises(ValueError, match="3.14"):
            loops.resolve_loop()

    def test_auto_never_picks_it(
        self, on_314: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even on 3.14 with zuvloop installed: it is 0.0.x, so it is opt-in.
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "auto")
        monkeypatch.setattr(loops.importlib.util, "find_spec", lambda name: object())

        assert loops.resolve_loop() == "uvloop"

    def test_uvicorn_hands_the_server_to_zuvloop(
        self, on_314: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        served: list[object] = []
        configs: list[dict[str, Any]] = []

        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "zuvloop")
        monkeypatch.setattr(settings, "AUTO_RELOAD", False)
        # The subject is the startup shape, not app construction. Building
        # the real integrated app here would drag in every service import
        # for no assertion.
        monkeypatch.setattr(webserver, "create_integrated_app", lambda: object())
        monkeypatch.setattr(
            webserver.uvicorn, "Config", lambda *a, **kw: configs.append(kw) or kw
        )
        monkeypatch.setattr(
            webserver.uvicorn, "Server", lambda config: _FakeServer(config)
        )
        monkeypatch.setattr(webserver, "_zuvloop_run", served.append)

        webserver.main()

        # uvicorn must be told to set up no loop of its own.
        assert configs[0]["loop"] == "none"
        assert served, "the server coroutine never reached zuvloop"

    def test_reload_with_zuvloop_is_refused(
        self, on_314: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # uvicorn's reloader is a supervisor that spawns child processes;
        # there is nowhere to hand zuvloop a coroutine.
        monkeypatch.setattr(settings, "WEBSERVER_LOOP", "zuvloop")
        monkeypatch.setattr(settings, "AUTO_RELOAD", True)

        with pytest.raises(ValueError, match="reload"):
            webserver.main()


class _FakeServer:
    def __init__(self, config: object) -> None:
        self.config = config

    def serve(self) -> str:
        return "coroutine"


def test_the_reload_supervisor_does_not_load_the_app() -> None:
    """With reload on, the process running the entrypoint only supervises:
    the worker it spawns imports the app from ``APP_TARGET``. Importing the
    entrypoint must not import the app, or the supervisor holds all of it -
    201 MB where 46 MB will do (#1444)."""
    import subprocess
    import sys

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.entrypoints.webserver; "
            "print('app.integrations.main' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert probe.stdout.strip() == "False"
