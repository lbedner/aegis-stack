"""The MCP app's lifespan (``app.components.mcp.http``), here rather than
in ``main.py``'s lifespan, which renders the same with MCP or without, so
adding MCP never touches it."""

from contextlib import AsyncExitStack

from app.components.mcp import http

# Left by the shutdown hook (``shutdown/mcp_lifespan.py``).
stack = AsyncExitStack()


async def startup_hook() -> None:
    """Start the MCP-over-HTTP app mounted at /mcp: a mounted app's
    lifespan does not run on its own, and without it no session starts."""
    if http.mounted is not None:
        await stack.enter_async_context(http.mounted.lifespan(http.mounted))
