"""Context for the Overseer Database page's sections.

The same four views as the Flet database modal's tabs, built by the same helpers
(``app.services.system.ui_database``) from the health check's metadata;
Transactions, what is open right now (``db_transactions``), kept live over
SSE, each with the way to end it; Rows, a table's rows a page at a time
(``db_rows``), read like Logs across the whole window, each row opening
to the rows its keys lead to (``row_links``), and Query, one
read-only statement's answer in the same scroller (``db_query``), both
where ``exposure.shown`` allows.
"""

import asyncio
from typing import Any

from fastapi import HTTPException

from app.core import exposure, series
from app.core.config import settings
from app.core.constants import ComponentName
from app.core.formatting import (
    counted,
    format_duration_ms,
    format_number,
    format_span,
    page_number,
)
from app.services.system import ui_database, ui_logs
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_database_subtitle

from . import overseer_container
from .overseer_live import fragments_events
from .overseer_nav import SectionRequest, page_url
from .rendering import fragment, status_cell, with_query

EVENTS = "/overseer/events/database/transactions"
EVENT = "database-transactions"
BODY = "pages/overseer/database/_transactions_body.html"
# Ending a Postgres connection: its confirm, then the API it calls.
END_CONFIRM = "/partials/overseer/database/connections/{pid}/end"
END_API = "/api/v1/database/connections/{pid}/end"
END_TITLE = "End connection"
ROWS = "rows"
ROWS_URL = page_url("components", ComponentName.DATABASE) + "/" + ROWS
QUERY = "query"
# Where the prompt posts its statement (audited), and what answers it.
QUERY_RUN = "/partials/overseer/database/query"
QUERY_ANSWER = "pages/overseer/database/_query_answer.html"

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "schema": "Schema",
            ROWS: "Rows",
            QUERY: "Query",
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
        context |= schema(metadata)
    elif section == "migrations":
        context["migrations"] = ui_database.migrations(metadata)
    elif section == "engine":
        context["settings"] = ui_database.settings(metadata)
    elif section == "activity":
        context["activity"] = ui_database.activity(metadata)
        context["threshold"] = settings.DATABASE_SLOW_TRANSACTION_SECONDS
    elif section in (ROWS, QUERY) and (off := exposure.refusal(exposure.ROWS)):
        context["rows_off"] = off
    elif section == ROWS:
        context |= await rows(req, metadata)
    elif section == QUERY:
        context["query_run"] = QUERY_RUN
    elif section == "transactions":
        context |= await transactions() | {
            "transactions_events": EVENTS,
            "transactions_event": EVENT,
        }
    return context


def _present(metadata: dict[str, Any]) -> list[str] | None:
    """The tables the health check found in the database, when it says."""
    found = metadata.get("table_schemas")
    return [t.get("name") for t in found] if found else None


def schema(metadata: dict[str, Any]) -> dict[str, Any]:
    """The Schema section: each table, its name leading to its rows where
    they are shown and the models declare it."""
    tables = ui_database.tables(metadata)
    if not exposure.shown(exposure.ROWS):
        return {"tables": tables, "tables_link": False}
    from app.services.system import db_rows  # with the database component

    readable = set(db_rows.tables(_present(metadata)))
    for table in tables:
        name = table["name"]
        url = with_query(ROWS_URL, table=name) if name in readable else None
        table["link"] = {"label": name, "url": url}
    return {"tables": tables, "tables_link": True}


async def rows(req: SectionRequest, metadata: dict[str, Any]) -> dict[str, Any]:
    """The Rows section: the table picked (``?table=``, the first by name
    otherwise), a page of it as the query orders and filters it, and the
    links to the pages either side. A table or column it may not read is
    not found."""
    from app.services.system import db_rows  # with the database component

    names = db_rows.tables(_present(metadata))
    query = req.query
    name = query.get("table") or (names[0] if names else "")
    table = db_rows.table_of(name) if name in names else None
    if table is None:
        raise HTTPException(status_code=404, detail=f"No table {name!r} to read.")
    asked = {
        "table": name,
        "order": query.get("order") or None,
        "dir": "desc" if query.get("dir") == "desc" else None,
        "where": query.get("where") or None,
    }
    picked = {"rows_tables": [{"id": n, "name": n} for n in names], "rows_asked": asked}
    try:
        found = await asyncio.to_thread(
            db_rows.page,
            table,
            order=asked["order"],
            desc=asked["dir"] == "desc",
            where=db_rows.parse_where(asked["where"]),
            after=query.get("after") or None,
            before=query.get("before") or None,
            number=page_number(query.get("page")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except db_rows.ReadTooSlowError as exc:
        return picked | {"rows_slow": str(exc)}
    count = next(
        (
            t.get("rows")
            for t in metadata.get("table_schemas") or []
            if t.get("name") == name
        ),
        None,
    )
    summary = counted(len(found.rows), "row")
    if count is not None:
        summary += (
            f" of {'~' if asked['where'] else ''}{format_number(count)} in {name}"
        )
    out, into = db_rows.keys(table)
    offered = set(names)
    return picked | {
        "rows": found,
        "rows_keys": list(dict.fromkeys(_key_label(k) for k in (*out, *into))),
        "rows_links": [
            row_links(found.columns, row, out, into, offered) for row in found.rows
        ],
        "rows_orders": [{"id": c, "name": c} for c in found.sortable],
        "rows_dirs": [
            {"id": k, "name": label} for k, label in reversed(ui_logs.ORDERS)
        ],
        "rows_pager": {
            "summary": summary,
            "next": with_query(req.path, **asked, **found.next) if found.next else None,
            "prev": with_query(req.path, **asked, **found.prev) if found.prev else None,
        },
    }


def _key_label(key: Any) -> str:
    """``member.org_id → org.id``, a composite key's columns together."""
    return f"{key.table}.{', '.join(key.columns)} → {key.target}.{', '.join(key.to)}"


def row_links(
    columns: list[str],
    row: list[str],
    out: list[Any],
    into: list[Any],
    offered: set[str],
) -> list[dict[str, str]]:
    """Where a row's keys lead (``db_rows.follow``): out to the row each
    points at, in to the rows pointing at it, each the Rows section
    filtered to them; only to a table it ``offered`` (one migrated)."""
    from app.services.system import db_rows  # with the database component

    cells = dict(zip(columns, row, strict=True))
    links = []
    for key, outward in [*((k, True) for k in out), *((k, False) for k in into)]:
        led = db_rows.follow(key, cells, out=outward)
        if led and led[0] in offered:
            table, where = led
            arrow = "→" if outward else "←"
            links.append(
                {
                    "label": f"{arrow} {table} {where}",
                    "url": with_query(ROWS_URL, table=table, where=where),
                }
            )
    return links


async def query(sql: str) -> tuple[str, dict[str, Any]]:
    """``sql`` run read-only (``db_query``): how it went, for the audit
    (ran, refused, stopped), and the answer's context: its rows and a
    footer line, or why there are none. Not found where rows are hidden."""
    from app.services.system import db_query, db_rows  # with the database component

    try:
        found = await asyncio.to_thread(db_query.run, sql)
    except db_rows.RowsHiddenError:
        raise HTTPException(status_code=404) from None
    except db_query.QueryError as exc:
        return "refused", {"query_error": str(exc)}
    except db_rows.ReadTooSlowError as exc:
        return "stopped", {"query_error": str(exc)}
    shown = counted(len(found.rows), "row")
    if found.more:
        shown = f"the first {format_number(db_query.LIMIT)} rows"
    footer = f"{shown} · {format_duration_ms(found.seconds * 1000)} · read-only"
    return "ran", {"rows": found, "query_footer": footer}


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
