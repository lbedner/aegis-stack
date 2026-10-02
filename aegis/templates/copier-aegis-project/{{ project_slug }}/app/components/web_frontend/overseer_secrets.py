"""Context for the Overseer Secrets page: every credential the app declares
(``app.core.secrets``), grouped by the code that reads it, with where it is
set, its last four characters and, once a store keeps them, when and by
whom. Never a value. For one that is missing, the ``.env`` line to add.

Read-only on the ``.env`` backend, where a value changes on restart; with
the secrets component a key not in ``.env`` is set, replaced or removed
here (``routes/partials/overseer_secrets.py``). An unset key reads Missing
when something enabled needs it, Not used when it is only a choice, and a
key with a provider check can be tested wherever it is set."""

from itertools import groupby
from typing import Any

from app.core import secrets
from app.core.formatting import format_relative_time
from app.services.system.models import ComponentStatus

from .overseer_nav import NavItem, SectionRequest
from .rendering import status_cell

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
# How each source reads on the page; another store reads as its own name
# ("vault" -> "Vault").
SOURCES = {secrets.ENV: ".env", "database": "Saved here"}
# A provider check's toast tone.
VERDICT_TONES = {
    secrets.VERIFIED: "ok",
    secrets.UNVERIFIED: "warn",
    secrets.REJECTED: "error",
}


def _row(row: secrets.SecretStatus, writable: bool) -> dict[str, Any]:
    if not row.is_set:
        # Needed by something enabled, or a provider this app could use.
        state = (
            status_cell("Missing", "warn")
            if row.needed
            else status_cell("Not used", "muted")
        )
        value = f"{row.name}=..."
    else:
        source = row.source or secrets.ENV
        state = status_cell(SOURCES.get(source, source.capitalize()), "ok")
        value = (f"•••• {row.hint}" if row.secret else row.hint) if row.hint else "Set"
    when = (
        f"{format_relative_time(row.set_at)}"
        + (f" by {row.set_by}" if row.set_by else "")
        if row.set_at
        else ""
    )
    return {
        "name": row.name,
        "label": row.label,
        "state": state,
        "shown": {"text": value, "missing": not row.is_set},
        "when": when,
        "editable": writable and row.live and row.source != secrets.ENV,
        # Read through ``settings``: only ``.env`` ever reaches that code.
        "env_only": writable and not row.live and row.source != secrets.ENV,
        "in_env": row.source == secrets.ENV,
        "testable": row.is_set and row.verifiable,
        "url": f"{PARTIALS}/{row.name}",
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
    writable = secrets.writable()
    return {
        "groups": [
            {"owner": owner, "rows": [_row(r, writable) for r in members]}
            for owner, members in groupby(rows, key=lambda r: r.owner)
        ],
        "writable": writable,
        "summary": _summary(rows),
        "store": (secrets.store_name() or "").capitalize(),
        "section_subtitle": "Every credential the app reads. Values are never shown.",
    }
