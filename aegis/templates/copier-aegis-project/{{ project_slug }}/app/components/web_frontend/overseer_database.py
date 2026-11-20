"""Context for the Overseer Database page's sections.

Overview, Migrations and Engine, built by the Flet database modal's
helpers (``app.services.system.ui_database``) from the health check's
metadata; Slow & locked, what ``db_activity`` kept, as
``ActivitySearch`` filters it, kept live over SSE;
Transactions, what is open right now (``db_transactions``), kept live over
SSE, each with the way to end it; Tables and Query, the database browser
(``overseer_database_browser``).
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.core import series
from app.core.config import settings
from app.core.formatting import counted, format_span
from app.services.system import ui_database, ui_logs
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_database_subtitle

from . import overseer_container, overseer_logs
from . import overseer_database_browser as browser
from .overseer_database_browser import QUERY, TABLES
from .overseer_live import fragment_events
from .overseer_nav import SectionRequest
from .rendering import fragment, status_cell, with_query

if TYPE_CHECKING:  # ships only with a database
    from app.services.system.db_activity_search import ActivitySearch

EVENTS = "/overseer/events/database/transactions"
EVENT = "database-transactions"
BODY = "pages/overseer/database/_transactions_body.html"
# Ending a Postgres connection: its confirm, then the API it calls.
END_CONFIRM = "/partials/overseer/database/connections/{pid}/end"
END_API = "/api/v1/database/connections/{pid}/end"
END_TITLE = "End connection"
# Slow & locked: its stream and the part the stream swaps.
ACTIVITY_EVENTS = "/overseer/events/database/activity"
ACTIVITY_EVENT = "database-activity"
ACTIVITY_BODY = "pages/overseer/database/_activity_body.html"
# How often the stream looks again: these are rare, so seconds, not a tick.
ACTIVITY_SECONDS = 5.0
# The newest rows shown; the groups count every one the filters keep.
ACTIVITY_ROWS = 200

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            TABLES: "Tables",
            QUERY: "Query",
            "migrations": "Migrations",
            "engine": "Engine",
            "activity": "Slow & locked",
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
    elif section == "migrations":
        context["migrations"] = ui_database.migrations(metadata)
    elif section == "engine":
        context["settings"] = ui_database.settings(metadata)
    elif section == "activity":
        context |= await activity_page(req.query)
    elif section == TABLES:
        context |= await browser.tables(req, metadata)
    elif section == QUERY:
        context |= browser.query_page(req, metadata)
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


async def activity_page(query: Mapping[str, str]) -> dict[str, Any]:
    """Slow & locked: its filters (``ActivitySearch``) and what they keep,
    with the stream that keeps it live."""
    # Not at import: the page ships with every stack, these with a database.
    from app.core import db_activity
    from app.services.system.db_activity_search import ActivitySearch

    search = ActivitySearch.of(query)
    return await activity(search) | {
        "activity_windows": db_activity.windows(),
        "activity_window": search.window,
        "activity_kinds": overseer_logs.options(
            ui_database.ACTIVITY_KINDS.items(), search.kinds
        ),
        "activity_services": overseer_logs.picker(await ui_logs.every_source(), query),
        "activity_q": search.text,
        "activity_events": with_query(
            ACTIVITY_EVENTS,
            window=str(search.window),
            kind=sorted(search.kinds),
            q=search.text,
            **ui_logs.picks(query),
        ),
        "activity_event": ACTIVITY_EVENT,
        "threshold": settings.DATABASE_SLOW_TRANSACTION_SECONDS,
    }


async def activity(search: "ActivitySearch") -> dict[str, Any]:
    """What ``search`` keeps of its window: by code, then the newest rows."""
    from app.services.system.db_activity_search import find_activity

    found = await find_activity(search, ACTIVITY_ROWS)
    return {
        "activity": found["rows"],
        "activity_more": found["more"],
        "activity_groups": found["groups"],
        "activity_none": ui_database.nothing_in(search.window),
    }


def activity_events(query: Mapping[str, str], max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """Slow & locked over SSE, as filtered, sent again only when it changes."""
    from app.services.system.db_activity_search import ActivitySearch

    search = ActivitySearch.of(query)

    async def render() -> str:
        return fragment(ACTIVITY_BODY, **await activity(search))

    return fragment_events(ACTIVITY_EVENT, render, ACTIVITY_SECONDS, max_frames)


def events(max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The Transactions table over SSE, sent again only when it changes."""

    async def render() -> str:
        return fragment(BODY, **await transactions())

    return fragment_events(EVENT, render, series.TICK_SECONDS, max_frames)
