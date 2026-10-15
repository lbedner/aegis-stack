"""Overseer > Database > Tables and Query, the database browser.

Tables, everything about a table in one place: its schema, its
relationships drawn as Overseer's map draws (``table_graph``), its rows a
page at a time (``db_rows``) read like Logs, each row opening to the rows
its keys lead to (``row_links``); and Query, read-only statements written
in an editor (sql.js keeps its tabs), each answer in the same scroller
(``db_query``). Rows and answers where ``exposure.shown`` allows.
"""

import asyncio
from typing import Any

from fastapi import HTTPException

from app.core import exposure
from app.core.constants import ComponentName
from app.core.formatting import counted, format_duration_ms, format_number, page_number
from app.services.system import topology, ui_database

from . import overseer_map
from .overseer_nav import SectionRequest, page_url
from .rendering import with_query

PAGE = page_url("components", ComponentName.DATABASE)
TABLES = "tables"
TABLES_URL = f"{PAGE}/{TABLES}"
# A table's tabs (``?tab=``); Rows first where they are shown.
ROWS = "rows"
SCHEMA = "schema"
RELATIONSHIPS = "relationships"
TABS = {ROWS: "Rows", SCHEMA: "Schema", RELATIONSHIPS: "Relationships"}
ROWS_PANE = "database-rows"  # what paging, sorting and filtering swap
QUERY = "query"
QUERY_URL = f"{PAGE}/{QUERY}"
# Where the prompt posts its statement (audited), and what answers it.
QUERY_RUN = "/partials/overseer/database/query"
QUERY_ANSWER = "pages/overseer/database/_query_answer.html"


def _listed(metadata: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """The tables the health check lists, by name (its ``table_schemas``:
    rows, columns, indexes, keys), and the names to offer: the listed, the
    models' where it lists none (``db_rows.tables``)."""
    from app.services.system import db_rows  # with the database component

    found = {t["name"]: t for t in metadata.get("table_schemas") or []}
    return found, sorted(found) or db_rows.tables()


async def tables(req: SectionRequest, metadata: dict[str, Any]) -> dict[str, Any]:
    """The Tables section: the database's tables under their schema, and
    the one picked (``?table=``, the first otherwise) on its tab (``?tab=``):
    Rows where they are shown and the models declare it, Schema otherwise;
    and the way to query it. A table the database does not have is not
    found; one the models do not declare has no rows or keys read."""
    from app.services.system import db_rows  # with the database component

    found, names = _listed(metadata)
    name = req.query.get("table") or (names[0] if names else "")
    if name not in names:
        raise HTTPException(status_code=404, detail=f"No table {name!r} to read.")
    readable = db_rows.tables(list(found) or None)
    table = db_rows.table_of(name) if name in readable else None
    off = exposure.refusal(exposure.ROWS)
    tab = req.query.get("tab") or ""
    if tab not in TABS:
        tab = ROWS if table is not None and not off else SCHEMA
    counts = {n: t.get("rows") for n, t in found.items()}
    context: dict[str, Any] = {
        "tables_schema": ui_database.schema_name(metadata),
        # Left out where only the rows are swapped: thrown away there.
        "tables_list": []
        if req.target == ROWS_PANE
        else [
            {
                "name": n,
                "rows": format_number(counts[n]) if counts.get(n) is not None else None,
                "url": with_query(TABLES_URL, table=n),
            }
            for n in names
        ],
        "table_name": name,
        "table_tab": tab,
        "table_query": with_query(QUERY_URL, table=name),
        "table_tabs": [
            {
                "key": key,
                "label": label,
                "url": with_query(TABLES_URL, table=name, tab=key),
            }
            for key, label in TABS.items()
        ],
        "table_unread": table is None,
        "rows_pane": ROWS_PANE,
    }
    if tab == SCHEMA:
        listed = found.get(name)
        context["table_sql"] = ui_database.create_table_sql(listed) if listed else None
    elif table is not None and tab == RELATIONSHIPS:
        context |= table_graph(table, set(names), counts)
    elif table is not None and off:
        context["rows_off"] = off
    elif table is not None:
        context |= await rows(req, table, counts.get(name), set(readable))
    return context


def query_page(req: SectionRequest, metadata: dict[str, Any]) -> dict[str, Any]:
    """The Query section: where the editor posts a statement, the dialect
    it highlights and the tables and columns it completes, and, from a
    table (``?table=``), the statement a new tab starts with, the table
    named as the dialect needs, and the tab's name. Where rows are hidden,
    why."""
    if off := exposure.refusal(exposure.ROWS):
        return {"rows_off": off}
    from sqlalchemy.dialects import postgresql, sqlite  # with the database component

    found, names = _listed(metadata)
    dialect = (postgresql if ui_database.is_postgres(metadata) else sqlite).dialect()
    asked = req.query.get("table") or ""
    seeded = asked in names
    return {
        "query_run": QUERY_RUN,
        "query_dialect": dialect.name,
        "query_schema": editor_schema(names, found),
        "query_seed": f"SELECT * FROM {dialect.identifier_preparer.quote(asked)}"
        if seeded
        else None,
        "query_seed_name": asked if seeded else None,
    }


def editor_schema(
    names: list[str], found: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    """Each table's column names, for the Query editor to complete: the
    health check's (``found``), the models' where it has not listed them."""
    from app.services.system import db_rows  # with the database component

    models = db_rows.by_name()
    return {
        name: [c.get("name", "?") for c in found[name].get("columns") or []]
        if name in found
        else list(models[name].columns.keys())
        if name in models
        else []
        for name in names
    }


def table_graph(
    table: Any, offered: set[str], counts: dict[str, int | None]
) -> dict[str, Any]:
    """A table's Relationships as Overseer's map draws them
    (``overseer_map.layout``, across): the tables pointing at it on the
    left, it in the middle, those it points at on the right (one pointing
    both ways too), a line for each pair; each a node with its rows and, on
    hover, the keys between them, leading to its own relationships where
    the database has it. A table pointing at itself says so on its node."""
    from app.services.system import db_rows  # with the database component

    name = table.name
    out, into = db_rows.keys(table)
    said: dict[str, list[str]] = {}
    for key in (*out, *into):
        other = key.target if key.table == name else key.table
        said.setdefault(other, []).append(_key_label(key))
    right = list(dict.fromkeys(k.target for k in out if k.target != name))
    left = [
        t
        for t in dict.fromkeys(k.table for k in into if k.table != name)
        if t not in right
    ]

    def node(table_name: str) -> dict[str, Any]:
        rows = counts.get(table_name)
        keys = said.get(table_name, [])
        here = table_name == name
        return {
            "key": table_name,
            "title": table_name,
            "url": with_query(TABLES_URL, table=table_name, tab=RELATIONSHIPS)
            if table_name in offered and not here
            else None,
            "tone": "ok",
            "figure": counted(rows, "row") if rows is not None else None,
            "message": "\n".join(keys) if not here else "This table.",
            "note": f"Points at itself: {', '.join(keys)}" if here and keys else None,
        }

    tiers = [tier for tier in (left, [name], right) if tier]
    shape = topology.Shape(
        tiers=tiers,
        links=[(t, name) for t in left] + [(name, t) for t in right],
        hosted=[],
    )
    return overseer_map.layout(
        [node(t) for tier in tiers for t in tier],
        shape,
        across=True,
        target="#database-table",
    ) | {"table_alone": not (left or right)}


async def rows(
    req: SectionRequest, table: Any, count: int | None, offered: set[str]
) -> dict[str, Any]:
    """A table's Rows tab (``_rows``), every read recorded: the rows are the
    app's data, so who read the table, as they asked, and how it went (ran,
    refused, stopped, failed)."""
    outcome, found = await _rows(req, table, count, offered)
    await req.audit("database.rows", outcome, table.name, **found["rows_asked"])
    return found


async def _rows(
    req: SectionRequest, table: Any, count: int | None, offered: set[str]
) -> tuple[str, dict[str, Any]]:
    """How the read went, and a table's Rows tab: a page of it as the query
    orders and filters it (the filters so far, ``where``, and one more: a
    ``column`` picked from those it may filter by, an ``op`` and a
    ``value``; those no index serves marked, as they read the table
    through), each filter a chip that takes it away, and the links to the
    pages either side; each row's keys lead to the tables ``offered``. What
    cannot be asked says so in place of the rows."""
    from app.services.system import db_filters, db_rows  # with the database component

    query = req.query
    name = table.name
    where = db_filters.parse_where(query.get("where"))
    value = query.get("value") or ""
    bad = None
    if (column := query.get("column")) and value.strip():
        try:
            where.append(db_filters.ask(column, query.get("op") or ":", value))
        except db_filters.AskError as exc:
            bad = str(exc)
    asked = {
        "table": name,
        "order": query.get("order") or None,
        "dir": "desc" if query.get("dir") == "desc" else None,
        "where": db_filters.where_text(where) or None,
    }
    indexed = set(db_rows.sortable(table))
    allowed = db_rows.filterable(table)
    picked = {
        "rows_asked": asked,
        "rows_filters": [
            {"id": c, "name": c if c in indexed else f"{c} (no index)"} for c in allowed
        ],
        # Which comparisons each column allows, for the page to offer only
        # those as a column is picked (no request; the server keeps them).
        "rows_allowed": {c: db_filters.operators(table.columns[c]) for c in allowed},
        "rows_ops": [
            {"id": key, "name": sign} for key, (sign, _) in db_filters.OPERATORS.items()
        ],
        "rows_chips": [
            {
                "label": f"{c} {db_filters.OPERATORS[o][0]} {v}",
                "url": with_query(
                    req.path,
                    **asked
                    | {
                        "where": db_filters.where_text(where[:i] + where[i + 1 :])
                        or None
                    },
                ),
            }
            for i, (c, o, v) in enumerate(where)
        ],
    }
    if bad:
        return "refused", picked | {"rows_bad": bad}
    try:
        found = await asyncio.to_thread(
            db_rows.page,
            table,
            order=asked["order"],
            desc=asked["dir"] == "desc",
            where=where,
            after=query.get("after") or None,
            before=query.get("before") or None,
            number=page_number(query.get("page")),
        )
    except db_filters.AskError as exc:
        return "refused", picked | {"rows_bad": str(exc)}
    except db_rows.ReadTooSlowError as exc:
        return "stopped", picked | {"rows_slow": str(exc)}
    except db_rows.RowsUnreadError as exc:
        return "failed", picked | {"rows_bad": str(exc)}
    summary = counted(len(found.rows), "row")
    if count is not None:
        summary += (
            f" of {'~' if asked['where'] else ''}{format_number(count)} in {name}"
        )
    out, into = db_rows.keys(table)
    return "ran", picked | {
        "rows": found,
        "rows_links": [
            row_links(found.columns, row, out, into, offered) for row in found.rows
        ],
        "rows_sorts": sorts(req.path, asked, found),
        "rows_pager": {
            "summary": summary,
            "next": with_query(req.path, **asked, **found.next) if found.next else None,
            "prev": with_query(req.path, **asked, **found.prev) if found.prev else None,
        },
    }


def sorts(path: str, asked: dict[str, Any], found: Any) -> dict[str, dict[str, Any]]:
    """The columns the server orders a table by (``found.sortable``), each
    the page ordered by it, the other way if it is already: the header
    links, the one ordered marked (``aria-sort``), by its key unasked."""
    ordered = asked["order"] or found.key
    now = "descending" if asked["dir"] == "desc" else "ascending"
    return {
        column: {
            "url": with_query(
                path,
                **asked
                | {
                    "order": column,
                    "dir": "desc" if column == ordered and now == "ascending" else None,
                },
            ),
            "sort": now if column == ordered else None,
        }
        for column in found.sortable
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
    points at, in to the rows pointing at it, each that table's rows
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
                    "url": with_query(TABLES_URL, table=table, where=where),
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
