"""Health check for the browser server (dashboard ComponentStatus).

Playwright's server answers plain HTTP on its WebSocket port, so one GET
says whether it is up without launching a browser.
"""

from enum import StrEnum
from importlib.metadata import version

import httpx

from app.components.browser.client import browser_url
from app.core.config import settings
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus, ComponentStatusType

CLIENT_VERSION = version("playwright")


class BrowserFact(StrEnum):
    """The keys this check publishes in ``metadata``; the card and modal
    read them back by these names."""

    ENDPOINT = "endpoint"
    CLIENT = "client"


async def check_browser_health() -> ComponentStatus:
    """Whether the browser server answers, and which client this app runs."""
    url = browser_url()
    metadata: dict[str, object] = {BrowserFact.ENDPOINT: url, BrowserFact.CLIENT: CLIENT_VERSION}
    try:
        async with httpx.AsyncClient(
            timeout=settings.HEALTH_CHECK_TIMEOUT_SECONDS
        ) as client:
            # ws -> http, wss -> https: the same port answers both.
            response = await client.get(url.replace("ws", "http", 1))
        up = response.status_code < 500
    except httpx.HTTPError:
        up = False
    return ComponentStatus(
        name=ComponentName.BROWSER,
        status=ComponentStatusType.HEALTHY if up else ComponentStatusType.UNHEALTHY,
        message="Browser server reachable" if up else f"Browser server not reachable at {url}",
        metadata=metadata,
    )
