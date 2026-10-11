"""Open the browser in the browser container: the app's one way in.

Launch options travel with the connection, so each caller picks its own
flags (a meeting bot wants fake media devices, a crawler does not).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json

from playwright.async_api import Browser, async_playwright

from app.core.config import settings
from app.core.constants import ComponentName


def browser_url() -> str:
    """The browser server's address from where this process runs: the
    compose service inside Docker, localhost (at `make serve`'s chosen
    port) from the host."""
    if settings.is_docker:
        return settings.BROWSER_URL
    return settings.localhost_url(
        settings.BROWSER_URL, {ComponentName.BROWSER}, settings.BROWSER_HOST_PORT
    )


@asynccontextmanager
async def connect(
    args: list[str] | None = None, *, headless: bool = True
) -> AsyncIterator[Browser]:
    """A browser launched in the container with ``args``, closed on exit."""
    launch = {"headless": headless, "args": args or []}
    # ponytail: one Playwright driver (a node process) per connect; share one
    # per process, started once and stopped at shutdown, when a caller loops.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect(
            browser_url(),
            headers={"x-playwright-launch-options": json.dumps(launch)},
        )
        try:
            yield browser
        finally:
            await browser.close()
