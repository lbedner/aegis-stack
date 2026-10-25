"""The MCP app's lifespan (``app.components.mcp.http``), here rather than
in ``main.py``'s lifespan, which renders the same with MCP or without, so
adding MCP never touches it."""

import asyncio

from fastmcp.server.http import StarletteWithLifespan

from app.components.backend import background
from app.components.mcp import http
from app.core import concurrency

# Its background task's name, stopped by the shutdown hook
# (``shutdown/mcp_lifespan.py``) if the server's closing has not already.
NAME = "mcp-lifespan"


async def startup_hook() -> None:
    """Start the MCP-over-HTTP app mounted at /mcp: a mounted app's
    lifespan does not run on its own, and without it no session starts.
    It runs in a task of its own, entered and left there, until the server
    starts closing (``concurrency.closing``): the server waits for every
    connection to close before the shutdown hooks run, and a client's
    session stays open until its lifespan ends."""
    if http.mounted is None:
        return
    started = asyncio.Event()
    running = background.start(NAME, _serve(http.mounted, started))
    waiting = asyncio.ensure_future(started.wait())
    await asyncio.wait({running, waiting}, return_when=asyncio.FIRST_COMPLETED)
    waiting.cancel()
    if running.done():
        running.result()  # it failed to start: so does the server


async def _serve(app: StarletteWithLifespan, started: asyncio.Event) -> None:
    async with app.lifespan(app):
        started.set()
        await concurrency.closing().wait()
