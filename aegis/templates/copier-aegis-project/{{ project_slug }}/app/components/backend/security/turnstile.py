"""Cloudflare Turnstile, the human check in front of guest sign-in.

The page renders Cloudflare's widget with ``TURNSTILE_SITE_KEY``; it posts
the token it was given as ``cf-turnstile-response``, and ``passed`` asks
Cloudflare whether that token is good. Off while either key is blank, so a
stack runs without an account at Cloudflare. Fails closed: when Cloudflare
cannot be reached, nobody is let through as a human.
"""

import httpx

from app.core.config import settings
from app.core.log import logger

FIELD = "cf-turnstile-response"
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def enabled() -> bool:
    """Whether the check is configured (both keys set)."""
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


async def passed(token: str | None, ip: str | None) -> bool:
    """Whether ``token`` is one Cloudflare gave a human just now; True
    while the check is off."""
    if not enabled():
        return True
    if not token:
        return False
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            reply = await client.post(VERIFY_URL, data=data)
        reply.raise_for_status()
        return bool(reply.json().get("success"))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("turnstile check failed; refusing", error=str(exc))
        return False
