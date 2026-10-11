"""Browser settings, kept out of config.py's size budget.

``Settings`` inherits these, so they read as ``settings.BROWSER_URL`` and
load from ``.env`` like every other setting.
"""

from pydantic_settings import BaseSettings


class BrowserSettings(BaseSettings):
    # Playwright's browser server: the compose service by default.
    BROWSER_URL: str = "ws://browser:3000/"
    # Host publish port chosen by `make serve` (loaded from .env.ports).
    # None = use the container port. See `browser_url()`.
    BROWSER_HOST_PORT: int | None = None
