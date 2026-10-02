"""Context for the Overseer Secrets page: every credential the app declares
(``app.core.secrets``), grouped by the code that reads it, with where it is
set, its last four characters and, once a store keeps them, when and by
whom. Never a value. For one that is missing, the ``.env`` line to add.

Read-only on the ``.env`` backend, where a value changes on restart; with
the secrets component a key not in ``.env`` is set, replaced or removed
here (``routes/partials/overseer_secrets.py``). An unset key reads Missing
when something enabled needs it, Not used when it is only a choice, and a
key with a provider check can be tested wherever it is set."""

from collections.abc import Callable
from importlib.util import find_spec
from itertools import groupby
from typing import Any

from app.core import secrets
from app.core.formatting import format_relative_time
from app.services.system.models import ComponentStatus

from .overseer_nav import NavItem, SectionRequest, page_url
from .rendering import status_cell, templates

SECTIONS = ((None, {"overview": "Overview"}),)
PARTIALS = "/partials/overseer/secrets"

ITEM = NavItem(
    group="secrets",
    name="secrets",
    title="Secrets",
    url="/overseer/secrets",
    status="",
    component=ComponentStatus(name="secrets", message=""),
)
# With the secrets component installed, its page under Components holds
# all of this (one home); without it, the page stays at the top level.
COMPONENT_URL = page_url("components", "secrets")


def has_component() -> bool:
    return find_spec("app.components.secrets") is not None


def url() -> str:
    """Where the Secrets page lives in this stack."""
    return COMPONENT_URL if has_component() else ITEM.url


templates.env.globals["secrets_page"] = url

# A provider check's toast tone.
VERDICT_TONES = {
    secrets.VERIFIED: "ok",
    secrets.UNVERIFIED: "warn",
    secrets.REJECTED: "error",
}


def updated(row: secrets.SecretStatus) -> str:
    """When a stored value was set, and by whom; nothing for ``.env``."""
    if not row.set_at:
        return ""
    by = f" by {row.set_by}" if row.set_by else ""
    return f"{format_relative_time(row.set_at)}{by}"


def page_context(
    rows: list[secrets.SecretStatus],
    row: Callable[[secrets.SecretStatus, bool], dict[str, Any]],
) -> dict[str, Any]:
    """Rows grouped by the code that reads them, and whether (and where)
    they can be changed: the Secrets and Settings pages alike."""
    writable = secrets.writable()
    return {
        "groups": [
            {"owner": owner, "rows": [row(r, writable) for r in members]}
            for owner, members in groupby(rows, key=lambda r: r.owner)
        ],
        "writable": writable,
        "store": (secrets.store_name() or "").capitalize(),
    }


def base_row(row: secrets.SecretStatus) -> dict[str, Any]:
    """What a Secrets or Settings row always carries."""
    return {
        "name": row.name,
        "label": row.label,
        "when": updated(row),
        "in_env": row.source == secrets.ENV,
        "url": f"{PARTIALS}/{row.name}",
    }


def _row(row: secrets.SecretStatus, writable: bool) -> dict[str, Any]:
    if not row.is_set:
        # Needed by something enabled, or a provider this app could use.
        state = status_cell(row.state, "warn" if row.needed else "muted")
        value = f"{row.name}=..."
    else:
        state = status_cell(row.state, "ok")
        value = (f"•••• {row.hint}" if row.secret else row.hint) if row.hint else "Set"
    return base_row(row) | {
        "state": state,
        "shown": {"text": value, "missing": not row.is_set},
        "editable": writable and row.live and row.source != secrets.ENV,
        # Read through ``settings``: only ``.env`` ever reaches that code.
        "env_only": writable and not row.live and row.source != secrets.ENV,
        "testable": row.is_set and row.verifiable,
    }


def _summary(rows: list[secrets.SecretStatus]) -> str:
    needed = [r for r in rows if r.needed]
    unused = sum(1 for r in rows if not r.needed and not r.is_set)
    return (
        f"{sum(r.is_set for r in needed)} of {len(needed)} needed keys set"
        f" · {unused} optional not used"
    )


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """The declared secrets by owner, and whether they can be changed here."""
    rows = await secrets.status()
    return page_context(rows, _row) | {
        "summary": _summary(rows),
        "section_subtitle": "Every credential the app reads. Values are never shown.",
    }
