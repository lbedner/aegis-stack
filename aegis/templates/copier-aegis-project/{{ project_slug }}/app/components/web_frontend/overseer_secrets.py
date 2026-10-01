"""Context for the Overseer Secrets page: every credential the app declares
(``app.core.secrets``), grouped by the code that reads it, with where it is
set, its last four characters and, once a store keeps them, when and by
whom. Never a value. For one that is missing, the ``.env`` line to add.

Read-only on the ``.env`` backend, where a value changes on restart; the
secrets component makes it writable."""

from itertools import groupby
from typing import Any

from app.core import secrets
from app.core.formatting import format_relative_time
from app.services.system.models import ComponentStatus

from .overseer_nav import NavItem, SectionRequest
from .rendering import status_cell

SECTIONS = ((None, {"overview": "Overview"}),)

ITEM = NavItem(
    group="secrets",
    name="secrets",
    title="Secrets",
    url="/overseer/secrets",
    status="",
    component=ComponentStatus(name="secrets", message=""),
)
SOURCES = {"env": ".env", "database": "Saved here"}


def _row(row: secrets.SecretStatus) -> dict[str, Any]:
    if not row.is_set:
        state, value = status_cell("Not set", "muted"), f"{row.name}=..."
    else:
        state = status_cell(SOURCES[row.source or "env"], "ok")
        value = (f"•••• {row.hint}" if row.secret else row.hint) if row.hint else "Set"
    when = (
        f"{format_relative_time(row.set_at)}" + (f" by {row.set_by}" if row.set_by else "")
        if row.set_at
        else ""
    )
    return {
        "name": row.name,
        "label": row.label,
        "state": state,
        "shown": {"text": value, "missing": not row.is_set},
        "when": when,
    }


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """The declared secrets by owner, and whether they can be changed here."""
    rows = await secrets.status()
    return {
        "groups": [
            {"owner": owner, "rows": [_row(r) for r in members]}
            for owner, members in groupby(rows, key=lambda r: r.owner)
        ],
        "writable": secrets.writable(),
        "section_subtitle": "Every credential the app reads. Values are never shown.",
    }
