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
from app.core.loops import ENGINE_LOOPS, resolve_loop
from app.integrations.main import create_integrated_app

# Import string rather than the app object: both engines need one to
# respawn reload workers in a fresh process.
APP_TARGET = "app.integrations.main:create_integrated_app"
# Every interface: the container publishes the port, nothing else reaches it.
HOST = "0.0.0.0"


def app_package_dir() -> Path:
    """The directory reload watchers are scoped to.

    Unscoped, a watcher covers the whole working directory, which in the
    dev container is the bind mount with the host's ``.venv`` in it; a
    ``uv sync`` on the host then restarts the server in a storm. Matches
    the scheduler's and worker's watchers in ``scripts/entrypoint.sh``.
    """
    return Path(__file__).resolve().parents[1]


def uvicorn_settings() -> dict[str, Any]:
    """What both uvicorn call sites share.

    One place on purpose: a server-level setting has to land on the reload
    path AND the production path, and a setting added to only one of them
    means dev and prod quietly serve differently. Proxy-header handling
    lands here when it arrives.
    """
    loop = resolve_loop()
    if loop not in ENGINE_LOOPS["uvicorn"]:
        raise ValueError(
            f"uvicorn cannot run on {loop!r}. It accepts "
            f"{', '.join(ENGINE_LOOPS['uvicorn'])}; granian accepts "
            f"{', '.join(ENGINE_LOOPS['granian'])}."
        )
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


def serve_uvicorn() -> None:
    if settings.AUTO_RELOAD:
        # When reload is enabled, uvicorn requires an import string
        uvicorn.run(
            APP_TARGET,
            factory=True,
            reload=True,
            reload_dirs=[str(app_package_dir())],
            timeout_graceful_shutdown=5,
            **uvicorn_settings(),
        )
        return

    # Use the integration layer (handles webserver hooks, service discovery, etc.)
    uvicorn.run(create_integrated_app(), **uvicorn_settings())


def serve_granian() -> None:
    # Imported here, not at module scope: the default engine must not need
    # the alternate one installed. A stale image that predates the granian
    # dependency keeps serving on uvicorn instead of failing to import.
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
        loop=Loops(resolve_loop()),
        websockets=True,
        reload=settings.AUTO_RELOAD,
        reload_paths=[app_package_dir()],
    ).serve()


def main() -> None:
    """Main webserver entry point"""
    setup_logging()
    engine = settings.WEBSERVER_ENGINE
    # The loop is named in the log because it is otherwise invisible:
    # nothing downstream reports which one a process ended up on.
    logger.info(f"Starting Aegis Stack Web Server ({engine} on {resolve_loop()})...")

    if engine == "uvicorn":
        serve_uvicorn()
        return
    if engine == "granian":
        serve_granian()
        return
    raise ValueError(
        f"Unknown WEBSERVER_ENGINE {engine!r}. Valid engines: uvicorn, granian."
    )


if __name__ == "__main__":
    # Granian spawns its workers rather than forking, so they re-import
    # this module. Serving from anywhere but behind this guard makes the
    # child re-enter main() and die in multiprocessing's bootstrap check.
    main()
