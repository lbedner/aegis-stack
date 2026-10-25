"""Leave the MCP app's lifespan the startup hook entered."""

from app.components.backend import background
from app.components.backend.startup import mcp_lifespan


async def shutdown_hook() -> None:
    """Stop the MCP-over-HTTP app the startup hook started, where the
    server's closing has not already (a server that takes its signals
    outside Python, a test)."""
    await background.stop(mcp_lifespan.NAME)
