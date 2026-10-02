"""Context for the Overseer Comms page's sections.

Comms keeps no history of its own, so the page is its channels: whether
each is set up, exactly which settings are missing (in the service's own
words), and a test send where a channel is ready. Registered only in
projects with the comms service (see ``overseer_sections``).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.core import secrets
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


async def domains_view() -> dict[str, Any]:
    """The Resend account's sending domains for the Email section: each with
    its status and a Check, or why there is no list (no key yet, or a
    send-only key that cannot list domains)."""
    from app.services.ops.adapters.resend import ResendAdapter

    view: dict[str, Any] = {"new_url": f"{PARTIALS}/domains/new", "rows": []}
    if not await secrets.get("RESEND_API_KEY"):
        return view | {
            "reason": "Set RESEND_API_KEY on the Secrets page to manage domains."
        }
    try:
        found = await ResendAdapter().list_domains()
    except Exception as exc:  # noqa: BLE001 - the reason is what the card shows
        return view | {"reason": f"Resend did not list domains: {exc}"}
    return view | {
        "rows": [
            {
                "name": d.domain,
                "status": status_cell(
                    d.status.capitalize(), "ok" if d.verified else "warn"
                ),
                "check_url": f"{PARTIALS}/domains/{d.domain}/check",
            }
            for d in found
        ]
    }


async def section_context(
    section: str, comms: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    context: dict[str, Any] = {"partials": PARTIALS}
    if section == "overview":
        return context | {"channels": [await channel(key) for key, *_ in CHANNELS]}
    if section == "email":
        return context | {
            "channel": await channel("email"),
            "domains": await domains_view(),
        }
    return context | {"sms": await channel("sms"), "voice": await channel("voice")}
