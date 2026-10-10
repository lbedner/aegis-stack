"""Leave the MCP app's lifespan the startup hook entered."""

from app.components.backend.startup import mcp_lifespan


async def shutdown_hook() -> None:
    """Stop the MCP-over-HTTP app the startup hook started."""
    await mcp_lifespan.stack.aclose()
