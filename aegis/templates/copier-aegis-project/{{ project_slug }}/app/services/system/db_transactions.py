"""The database's transactions open right now, for the Database page's
Transactions view, and the way to end one.

Postgres says it all itself (``pg_stat_activity``): every connection, its
state, how long its transaction has been open, what it waits on and whom
it blocks; each process names its connections (``application_name``), and
one is ended with ``pg_terminate_backend``. SQLite keeps no such record, so
each process publishes the transactions it holds (``db_activity.held``),
with the code that opened them and the container they run in: ending one
means restarting that container. Past ``DATABASE_SLOW_TRANSACTION_SECONDS``
a transaction is trouble. No UI framework imports.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import text

from app.core import db_activity, series
from app.core.db import async_engine
from app.services.system import ui_runtime

# Every client connection to this database but the one asking.
_ACTIVITY = text(
    "SELECT pid, application_name, state,"
    " EXTRACT(EPOCH FROM now() - xact_start) AS xact_seconds,"
    " NULLIF(concat_ws(': ', wait_event_type, wait_event), '') AS wait,"
    " pg_blocking_pids(pid) AS blocked_by, query"
    " FROM pg_stat_activity"
    " WHERE datname = current_database() AND pid <> pg_backend_pid()"
    " AND backend_type = 'client backend'"
    " ORDER BY xact_start NULLS LAST"
)
_END = text(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
    " WHERE pid = :pid AND datname = current_database()"
    " AND pid <> pg_backend_pid()"
)


def is_postgres() -> bool:
    return async_engine.dialect.name == "postgresql"


async def current() -> dict[str, Any]:
    """``{"rows", "postgres"}``: each transaction (on
    Postgres, each connection) the oldest first, ``{"pid", "process",
    "code", "container", "state", "seconds", "wait", "blocked_by",
    "query", "trouble"}``, whichever the engine knows."""
    postgres = is_postgres()
    rows = await (_postgres() if postgres else _sqlite())
    return {"rows": rows, "postgres": postgres}


async def _sqlite() -> list[dict[str, Any]]:
    held = await db_activity.held()
    by_host = await containers() if held else {}
    now = datetime.now(UTC)
    rows = []
    for entry in held:
        seconds = (now - datetime.fromisoformat(entry["began"])).total_seconds()
        found = container_of(by_host, entry["host"])
        rows.append(
            {
                "pid": None,
                "process": entry["process"],
                "code": entry["caller"],
                "container": found.name if found else None,
                "state": "Holds the write lock"
                if entry.get("locks")
                else "Open (locks once it writes)",
                "seconds": seconds,
                "wait": None,
                "blocked_by": [],
                "query": "",
                "trouble": db_activity.is_slow(seconds),
            }
        )
    return rows


class SampledContainer(NamedTuple):
    """A container as the sampler last saw it: the Overseer page it shows
    on, and its name."""

    page: str
    name: str


async def containers() -> dict[str, SampledContainer]:
    """Each container by its hostname (``container_of``)."""
    tables = await series.latest(ui_runtime.SAMPLER) or {}
    return {
        row["id"][:12]: SampledContainer(page, row["name"])
        for page, view in tables.items()
        for row in view["rows"]
        if row.get("id")
    }


def container_of(
    by_host: Mapping[str, SampledContainer], host: str
) -> SampledContainer | None:
    """The container a process ran in, by its hostname: Docker's is the
    container's id, short."""
    return by_host.get(host[:12])


async def _pg_activity() -> list[dict[str, Any]]:
    async with async_engine.connect() as conn:
        result = await conn.execute(_ACTIVITY)
        return [dict(row) for row in result.mappings()]


async def _postgres() -> list[dict[str, Any]]:
    return [
        {
            "pid": row["pid"],
            "process": row["application_name"] or "-",
            "code": "",
            "container": None,
            "state": row["state"] or "-",
            "seconds": None
            if row["xact_seconds"] is None
            else float(row["xact_seconds"]),
            "wait": row["wait"],
            "blocked_by": list(row["blocked_by"] or []),
            "query": row["query"] or "",
            "trouble": row["xact_seconds"] is not None
            and db_activity.is_slow(row["xact_seconds"]),
        }
        for row in await _pg_activity()
    ]


async def end(pid: int) -> bool:
    """End one of this database's Postgres connections (never the one
    asking), rolling back its transaction: whether there was one to end."""
    async with async_engine.connect() as conn:
        return bool(await conn.scalar(_END, {"pid": pid}))
