#!/usr/bin/env python3
"""
Web server entry point for Aegis Stack.
Runs FastAPI + Flet only (clean separation of concerns).

The ASGI server is chosen at run time by ``WEBSERVER_ENGINE``, which
``make serve ENGINE=granian`` sets for one run. Both engines serve the
same app object; nothing about the application changes with the choice.
"""

from pathlib import Path
from typing import Any

import uvicorn

from app.core.config import settings
from app.core.log import logger, setup_logging
from app.core.loops import check_engine_loop, resolve_loop
from app.integrations.main import create_integrated_app

# Import string rather than the app object: both engines need one to
# respawn reload workers in a fresh process.
APP_TARGET = "app.integrations.main:create_integrated_app"
# Every interface: the container publishes the port, nothing else reaches it.
HOST = "0.0.0.0"
# Seconds a reload waits for the old worker before killing it. A clean
# stop takes milliseconds; this only ever cuts off one that is stuck.
RELOAD_KILL_TIMEOUT = 5


def app_package_dir() -> Path:
    """The directory reload watchers are scoped to.

    Unscoped, a watcher covers the whole working directory, which in the
    dev container is the bind mount with the host's ``.venv`` in it; a
    ``uv sync`` on the host then restarts the server in a storm. Matches
    the scheduler's and worker's watchers in ``scripts/entrypoint.sh``.
    """
    return Path(__file__).resolve().parents[1]


def uvicorn_settings(loop: str) -> dict[str, Any]:
    """What both uvicorn call sites share.

    One place on purpose: a server-level setting has to land on the reload
    path AND the production path, and a setting added to only one of them
    means dev and prod quietly serve differently. Proxy-header handling
    lands here when it arrives.
    """
    check_engine_loop("uvicorn", loop)
    return {
        "host": HOST,
        "port": settings.PORT,
        "loop": loop,
        # Uvicorn's websockets layer pings every 20s and drops the socket
        # when a proxy delays the pong, which killed Flet's connection
        # behind Traefik. Granian needs no equivalent; it sends no ping.
        "ws_ping_interval": None,
        "ws_ping_timeout": None,
    }


def _zuvloop_run(coro: Any) -> None:
    """Run a coroutine on zuvloop's loop.

    Indirected so tests can stand in for it without importing a Zig
    extension, and imported lazily so 3.13 never reaches for it.
    """
    import zuvloop

    zuvloop.run(coro)


def serve_zuvloop(loop: str) -> None:
    """uvicorn on zuvloop.

    ``uvicorn.run()`` owns the event loop, so a loop uvicorn does not know
    by name is unreachable through it. ``loop="none"`` is uvicorn's hook
    for that: it sets up nothing, and whoever calls ``Server.serve()``
    supplies the loop.
    """
    config = uvicorn.Config(
        create_integrated_app(), **{**uvicorn_settings(loop), "loop": "none"}
    )
    _zuvloop_run(uvicorn.Server(config).serve())


def serve_uvicorn(loop: str) -> None:
    if loop == "zuvloop":
        if settings.AUTO_RELOAD:
            # uvicorn's reloader is a supervisor that spawns child
            # processes; there is no coroutine to hand zuvloop.
            raise ValueError(
                "zuvloop cannot be used with reload. Run with AUTO_RELOAD "
                "off, or develop on uvloop and deploy on zuvloop."
            )
        serve_zuvloop(loop)
        return

    if settings.AUTO_RELOAD:
        # When reload is enabled, uvicorn requires an import string
        uvicorn.run(
            APP_TARGET,
            factory=True,
            reload=True,
            reload_dirs=[str(app_package_dir())],
            timeout_graceful_shutdown=5,
            **uvicorn_settings(loop),
        )
        return

    # Use the integration layer (handles webserver hooks, service discovery, etc.)
    uvicorn.run(create_integrated_app(), **uvicorn_settings(loop))


def serve_granian(loop: str) -> None:
    # Imported here, not at module scope: the default engine must not need
    # the alternate one installed. A stale image that predates the granian
    # dependency keeps serving on uvicorn instead of failing to import.
    check_engine_loop("granian", loop)

    from granian import Granian
    from granian.constants import Interfaces, Loops

    # No websocket ping settings to mirror from the uvicorn path: granian
    # sends no server-initiated keepalive ping, so the timeout that closed
    # Flet's socket behind a proxy has no equivalent here.
    Granian(
        target=APP_TARGET,
        factory=True,
        address=HOST,
        port=settings.PORT,
        interface=Interfaces.ASGI,
        loop=Loops(loop),
        websockets=True,
        reload=settings.AUTO_RELOAD,
        reload_paths=[app_package_dir()],
        # Granian defaults this off, so a worker that exits is never
        # replaced. On in dev, off in production where the container
        # healthcheck already restarts a dead server and respawning
        # would hide a crashloop.
        #
        # Measured caveat: this does NOT rescue a reload into code that
        # fails to import. Granian still tears the server down, and the
        # repaired file does not bring it back. The flag covers a worker
        # that dies while running, not one that dies on the way up.
        respawn_failed_workers=settings.AUTO_RELOAD,
        # Granian waits on a stopping worker forever by default, and a
        # worker holding an open dashboard websocket never finishes
        # stopping: a reload then leaves nothing on the port. Bounded in
        # dev only; in production a stop is a deploy, which the container
        # runtime already bounds.
        workers_kill_timeout=RELOAD_KILL_TIMEOUT if settings.AUTO_RELOAD else None,
    ).serve()


def main() -> None:
    """Main webserver entry point"""
    setup_logging()
    engine = settings.WEBSERVER_ENGINE
    # Resolved once, here, and carried. Four separate calls agreed only
    # because the function is deterministic; the log line in particular
    # must name the loop that actually runs, not one computed again.
    loop = resolve_loop()
    # Named in the log because it is otherwise invisible: nothing
    # downstream reports which one a process ended up on.
    logger.info(f"Starting Aegis Stack Web Server ({engine} on {loop})...")

    if engine == "uvicorn":
        serve_uvicorn(loop)
        return
    if engine == "granian":
        serve_granian(loop)
        return
    raise ValueError(
        f"Unknown WEBSERVER_ENGINE {engine!r}. Valid engines: uvicorn, granian."
    )


if __name__ == "__main__":
    # Granian spawns its workers rather than forking, so they re-import
    # this module. Serving from anywhere but behind this guard makes the
    # child re-enter main() and die in multiprocessing's bootstrap check.
    main()
