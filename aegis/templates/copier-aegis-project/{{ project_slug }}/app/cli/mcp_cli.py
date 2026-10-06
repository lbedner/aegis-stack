"""``mcp``: serve this app's granted tools to an MCP client over stdio."""

import sys

from app.core.config import settings
from app.core.log import logger, setup_logging
from app.core.tools import load_tools


async def serve() -> None:
    """Serve the granted tools (MCP_TOOLS) to an MCP client over stdio.

    Point a client at it: ``uv run <app> mcp``, or in Docker
    ``docker compose exec -T webserver <app> mcp`` (``-T``: a TTY would
    corrupt the stream).
    """
    # Imported here, not at the top: every CLI command imports this module
    # to register ``mcp``, and only this one needs FastMCP loaded.
    from app.components.mcp.server import build_server, served_effects

    try:  # kept on the record where there is a database to keep it in
        from app.components.mcp.activity import record
    except ImportError:
        from app.components.mcp.server import log_call as record

    # stdout carries the protocol and nothing else: one stray log line
    # there and the client reads garbage.
    setup_logging(stream=sys.stderr)
    load_tools()
    logger.info("mcp.serving", tools=list(served_effects(settings.MCP_TOOLS)))
    await build_server(settings.MCP_TOOLS, record=record).run_stdio_async(
        show_banner=False
    )
