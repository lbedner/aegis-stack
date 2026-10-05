"""Health check for the MCP component (dashboard ComponentStatus): how many
granted tools a client is served. A warning when it is served none, since
a client that connects then sees nothing to call."""

from app.services.system import ui_mcp
from app.services.system.models import ComponentStatus, ComponentStatusType

async def check_mcp_health() -> ComponentStatus:
    grant = ui_mcp.grant()
    served, dropped = len(grant["served"]), len(grant["dropped"])
    return ComponentStatus(
        name=ui_mcp.NAME,
        status=ComponentStatusType.HEALTHY if served else ComponentStatusType.WARNING,
        message=(
            f"{served} tool{'' if served == 1 else 's'} served"
            if served
            else ui_mcp.NONE_SERVED
        ),
        metadata={"served": served, "dropped": dropped, "transport": "stdio"},
    )
