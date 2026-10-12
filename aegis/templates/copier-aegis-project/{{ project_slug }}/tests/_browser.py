"""The browser container's browser, for the tests that drive a real page."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser
import pytest

from app.components.browser import health
from app.components.browser.client import connect
from app.services.system.models import ComponentStatusType


@asynccontextmanager
async def live_browser() -> AsyncIterator[Browser]:
    """A browser in the browser container; skips the test when none is up."""
    if (await health.check_browser_health()).status != ComponentStatusType.HEALTHY:
        pytest.skip("browser server not running (start it with `make serve`)")
    async with connect() as browser:
        yield browser
