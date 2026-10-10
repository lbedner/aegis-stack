"""The whole app's health, from any process.

Health checks register when the webserver starts, so only the webserver's
walk sees every component; any other process (the CLI, a chat turn in a
worker, the MCP server over stdio) has none of its own. ``live_status``
walks here when the checks are here, else asks the webserver's
``/health/detailed``, and falls back to this process's walk with a note
saying how little that sees.
"""

import httpx

from app.core.config import settings
from app.core.constants import APIEndpoints, Defaults
from app.core.log import logger
from app.services.system import health
from app.services.system.models import DetailedHealthResponse, SystemStatus

PARTIAL = (
    "The webserver did not answer, so this is only what this process can "
    "see: no component checks. Start the app for its full health."
)


async def live_status() -> tuple[SystemStatus, str | None]:
    """The app's health and, when it is partial, why."""
    if any(health.registered_health_names().values()):
        return await health.get_system_status(), None
    try:
        return await _from_webserver(), None
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("live_status.webserver_unreachable", error=str(exc))
    return await health.get_system_status(), PARTIAL


async def _from_webserver() -> SystemStatus:
    url = f"{settings.API_BASE_URL}{APIEndpoints.HEALTH_DETAILED}"
    async with httpx.AsyncClient(timeout=Defaults.API_TIMEOUT) as client:
        response = await client.get(url)
    response.raise_for_status()
    found = DetailedHealthResponse.model_validate(response.json())
    return SystemStatus.model_validate(
        {
            "components": found.components,
            "overall_healthy": found.healthy,
            "timestamp": found.timestamp,
            "system_info": found.system_info,
        }
    )
