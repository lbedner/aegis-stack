"""Context for the Overseer Comms page's sections.

Comms keeps no history of its own, so the page is its channels: whether
each is set up, exactly which settings are missing (in the service's own
words), and a test send where a channel is ready. Registered only in
projects with the comms service (see ``overseer_sections``).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.comms.calls import get_call_status, validate_call_config
from app.services.comms.email import get_email_status, validate_email_config
from app.services.comms.sms import get_sms_status, validate_sms_config
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest
from .rendering import status_cell

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Channels", {"email": "Email", "sms": "SMS and voice"}),
)

PARTIALS = "/partials/overseer/comms"

# (key, title, status, validate)
CHANNELS: tuple[
    tuple[
        str,
        str,
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[], Awaitable[list[str]]],
    ],
    ...,
] = (
    ("email", "Email", get_email_status, validate_email_config),
    ("sms", "SMS", get_sms_status, validate_sms_config),
    ("voice", "Voice", get_call_status, validate_call_config),
)


async def channel(key: str) -> dict[str, Any]:
    """One channel: configured or not, where it sends from, what is missing."""
    _, title, status, validate = next(c for c in CHANNELS if c[0] == key)
    state = await status()
    configured = bool(state.get("configured"))
    return {
        "key": key,
        "title": title,
        "provider": str(state.get("provider", "")).title(),
        "configured": configured,
        "badge": status_cell("Configured", "ok")
        if configured
        else status_cell("Not configured", "muted"),
        "sender": state.get("from_email") or state.get("phone_number"),
        "missing": [] if configured else await validate(),
    }


async def section_context(
    section: str, comms: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    context: dict[str, Any] = {"partials": PARTIALS}
    if section == "overview":
        return context | {"channels": [await channel(key) for key, *_ in CHANNELS]}
    if section == "email":
        return context | {"channel": await channel("email")}
    return context | {"sms": await channel("sms"), "voice": await channel("voice")}
