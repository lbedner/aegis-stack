"""Context for the Overseer Database page's sections.

The same four views as the Flet database modal's tabs, built by the same helpers
(``app.services.system.ui_database``) from the health check's metadata; and
Transactions, what is open right now (``db_transactions``), kept live over
SSE, each with the way to end it.
"""

from typing import Any

from app.core import series
from app.core.config import settings
from app.core.formatting import counted, format_span
from app.services.system import ui_database
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_database_subtitle

from . import overseer_container
from .overseer_live import fragments_events
from .overseer_nav import SectionRequest
from .rendering import fragment, status_cell

EVENTS = "/overseer/events/database/transactions"
EVENT = "database-transactions"
BODY = "pages/overseer/database/_transactions_body.html"
# Ending a Postgres connection: its confirm, then the API it calls.
END_CONFIRM = "/partials/overseer/database/connections/{pid}/end"
END_API = "/api/v1/database/connections/{pid}/end"
END_TITLE = "End connection"

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "schema": "Schema",
            "migrations": "Migrations",
            "engine": "Engine",
            "activity": "Activity",
            "transactions": "Transactions",
        },
    ),
)


async def section_context(
    section: str, database: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the database status."""
    metadata = database.metadata or {}
    context: dict[str, Any] = {"subtitle": get_database_subtitle(metadata)}
    if section == "overview":
        url = ui_database.display_url(str(metadata.get("url", "Unknown")))
        context["overview"] = ui_database.overview(metadata) | {"url": url}
    elif section == "schema":
        context["tables"] = ui_database.tables(metadata)
    elif section == "migrations":
        context["migrations"] = ui_database.migrations(metadata)
    elif section == "engine":
        context["settings"] = ui_database.settings(metadata)
    elif section == "activity":
        context["activity"] = ui_database.activity(metadata)
        context["threshold"] = settings.DATABASE_SLOW_TRANSACTION_SECONDS
    elif section == "transactions":
        context |= await transactions() | {
            "transactions_events": EVENTS,
            "transactions_event": EVENT,
        }
    return context


async def transactions() -> dict[str, Any]:
    """The open transactions as the table shows them: how long each has
    been open (red past the slow threshold), and where its Restart (SQLite:
    its container) or End (Postgres: its connection) confirms."""
    # Not at import: the page ships with every stack, db_transactions only
    # with the database component.
    from app.core import db_activity
    from app.services.system import db_transactions

    found = await db_transactions.current()
    rows = [
        row
        | {
            "id": row["pid"] or index,
            "open_for": status_cell(
                format_span(row["seconds"]) or "-",
                "error" if row["trouble"] else "muted",
            ),
            "end_url": END_CONFIRM.format(pid=row["pid"])
            if row["pid"]
            else overseer_container.RESTART.format(name=row["container"])
            if row["container"]
            else None,
        }
        for index, row in enumerate(found["rows"])
    ]
    noun = "connection" if found["postgres"] else "transaction held"
    plural = None if found["postgres"] else "transactions held"
    return {
        "transactions": rows,
        "transactions_postgres": found["postgres"],
        "transactions_summary": counted(len(rows), noun, plural),
        "threshold": settings.DATABASE_SLOW_TRANSACTION_SECONDS,
        "shown_after": db_activity.SHOWN_AFTER,
    }


def events(max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The Transactions table over SSE, sent again only when it changes."""

    async def frame() -> dict[str, str]:
        return {EVENT: fragment(BODY, **await transactions())}

    return fragments_events(frame, series.TICK_SECONDS, max_frames)
