"""Guest sign-in settings (``auth[guest]``), kept out of config.py's size
budget.

``Settings`` inherits these, so they load from ``.env`` like every other
setting.
"""

from typing import Annotated

from pydantic_settings import BaseSettings

from app.core.configurable import Configurable


class GuestSettings(BaseSettings):
    GUEST_SESSION_HOURS: Annotated[int, Configurable("service_auth", "Hours a guest's session lasts without use")] = 24
    RATE_LIMIT_GUEST_MAX: Annotated[int, Configurable("service_auth", "Guest sessions one address may start per window")] = 5
    RATE_LIMIT_GUEST_WINDOW: Annotated[int, Configurable("service_auth", "Seconds the guest limit counts over")] = 3600
    # Cloudflare Turnstile, the human check in front of guest sign-in. Off
    # while either key is blank.
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""
    # Live calls every guest together may hold at once, on a chat mount
    # open to guests (``web_frontend/guest_chat.py``); 0 is no cap.
    AI_GUEST_CONCURRENT_CALLS: Annotated[int, Configurable("service_ai", "Live calls guests may hold at once (0: no cap)")] = 3
