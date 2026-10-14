"""One read-only SQL statement, as Overseer runs it (Database > Query),
shown only where a table's rows are (``db_rows.require_shown``); Overseer's
page asks an admin (``overseer_actor``) and audits every run.

A write fails by construction, never by reading the SQL: the connection is
``db_rows.reading``'s, which only reads and stops past ``db_rows.SECONDS``.
One statement at a time; ``LIMIT`` rows, saying when there were more.

A secret never leaves the database. SQLite reads every column the models
hold one in as empty, however the statement reaches it (``reading``).
Postgres cannot, so a statement whose plan reads a table holding one is
refused (``secret_read``): that table's rows are on Rows, masked. Postgres
also runs only as a login that is not a superuser outside dev (a read-only
transaction does not stop a superuser's ``COPY ... TO PROGRAM`` or server
file reads), on a connection closed after it, so nothing it set outlives
it. Every cell goes through the same redaction and cut as a table's rows."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import json
import time
from typing import Any

from sqlalchemy import Connection, Engine, MetaData
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.services.system import db_rows

LIMIT = 200  # rows an answer shows
SUPERUSER = (
    "This database login is a superuser, which a read-only transaction does "
    "not stop (COPY ... TO PROGRAM, reading the server's files). Outside dev, "
    "Query runs only as a login that is not one."
)


class QueryError(Exception):
    """The statement was refused, or the database would not run it."""


@dataclass(frozen=True)
class Answer:
    """A statement's rows as text, its columns, those hidden, whether it
    had more than ``LIMIT``, and how long it ran."""

    columns: list[str]
    rows: list[list[str]]
    masked: frozenset[str]
    more: bool
    seconds: float


def statement(sql: str) -> str:
    """``sql`` as one statement (a trailing ``;`` dropped); QueryError
    otherwise (Postgres would run several sent at once)."""
    one = sql.strip().rstrip(";").strip()
    if not one:
        raise QueryError("Type a statement to run.")
    if ";" in one:
        raise QueryError("One statement at a time (no ; inside it).")
    return one


def run(
    sql: str, *, metadata: MetaData | None = None, engine: Engine | None = None
) -> Answer:
    """``sql``'s first ``LIMIT`` rows, read only. Raises RowsHiddenError
    where rows are not shown, QueryError for a statement refused or failed,
    ReadTooSlowError past ``db_rows.SECONDS``."""
    db_rows.require_shown()
    one = statement(sql)
    hidden = db_rows.secrets(metadata)
    started = time.monotonic()
    try:
        with db_rows.reading(engine, metadata) as conn:
            postgres = conn.dialect.name != "sqlite"
            try:
                if postgres:
                    _vet(conn, one, hidden)
                streamed = conn.execution_options(
                    stream_results=True, max_row_buffer=LIMIT + 1
                )
                result = streamed.exec_driver_sql(one)
                if not result.returns_rows:
                    raise QueryError("It returned no rows.")
                columns = list(result.keys())
                found = result.fetchmany(LIMIT + 1)
            finally:
                if postgres:
                    conn.invalidate()
    except DBAPIError as exc:  # past its time, ``reading`` has said so
        raise QueryError(str(exc.orig)) from None
    masked = frozenset(columns) & frozenset().union(*hidden.values())
    return Answer(
        columns=columns,
        rows=[
            [db_rows.HIDDEN if n in masked else _cell(v) for n, v in zip(columns, row)]
            for row in found[:LIMIT]
        ],
        masked=masked,
        more=len(found) > LIMIT,
        seconds=time.monotonic() - started,
    )


def _vet(conn: Connection, one: str, hidden: Mapping[str, frozenset[str]]) -> None:
    """Refuse, on Postgres, a superuser outside dev, and a statement whose
    plan reads a table holding a secret (planning runs nothing)."""
    superuser = conn.exec_driver_sql("SELECT current_setting('is_superuser')")
    if superuser.scalar() == "on" and not settings.is_dev:
        raise QueryError(SUPERUSER)
    plan = conn.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {one}").scalar()
    if name := secret_read(json.loads(plan) if isinstance(plan, str) else plan, hidden):
        raise QueryError(
            f"{name} holds a secret, which Postgres cannot blank in an answer: "
            "read it on Rows, where it is hidden."
        )


def secret_read(plan: Any, hidden: Mapping[str, frozenset[str]]) -> str | None:
    """The first table holding a secret that ``plan`` (``EXPLAIN (FORMAT
    JSON)``) reads, or None."""
    return next((name for name in _relations(plan) if name in hidden), None)


def _relations(plan: Any) -> Iterator[str]:
    """Every table a plan's nodes read, however deep."""
    if isinstance(plan, dict):
        if "Relation Name" in plan:
            yield plan["Relation Name"]
        for value in plan.values():
            yield from _relations(value)
    elif isinstance(plan, list):
        for value in plan:
            yield from _relations(value)


def _cell(value: Any) -> str:
    binary = isinstance(value, bytes | memoryview)
    return db_rows.cell(len(value) if binary else value, binary)
