"""One read-only SQL statement, as Overseer runs it (Database > Query),
shown only where a table's rows are (``db_rows.require_shown``); Overseer's
page asks an admin (``overseer_actor``) and audits every run.

A write fails by construction, never by reading the SQL: the connection is
``db_rows.reading``'s, which only reads and stops past ``db_rows.SECONDS``.
One statement at a time; ``LIMIT`` rows, saying when there were more.

A secret never leaves the database. SQLite reads every column the models
hold one in as empty, however the statement reaches it (``reading``).
Postgres runs the statement as the login's reader, a role that may read
every table but not the columns holding a secret (``grants``, set up once a
process: ``reader_role``); setting it also drops a superuser's powers. Where the
login cannot make that role, a statement whose plan reads a table holding a
secret is refused (``secret_read``), and a superuser login outside dev (a
read-only transaction does not stop its ``COPY ... TO PROGRAM``). Either
way, what a plan names but never shows into is refused (``unseen``), and
the connection is closed after, so nothing it set outlives it. Every cell
goes through the same redaction and cut as a table's rows."""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import json
import re
import time
from typing import Any

from sqlalchemy import Connection, Engine, MetaData, Table
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.log import logger
from app.services.system import db_rows

LIMIT = 200  # rows an answer shows
# What a plan names but never shows into, so a secret could pass unseen:
# SQL run inside a function, the planner's samples of every column
# (``pg_stats`` reads ``pg_statistic``), another connection ended (a
# read-only transaction does not stop it).
# Refused with the reader role too: it keeps the secrets, and this keeps
# what it would let through (another connection's backend ended, a
# notification sent) and stands where the role could not be made.
UNSEEN = re.compile(
    r"\b(query_to_xml\w*|table_to_xml\w*|cursor_to_xml\w*|schema_to_xml\w*"
    r"|database_to_xml\w*|ts_stat|ts_rewrite|dblink\w*|pg_statistic(?:_ext_data)?"
    r"|pg_terminate_backend|pg_cancel_backend|pg_notify)\b"
)
SUPERUSER = (
    "This database login is a superuser, which a read-only transaction does "
    "not stop (COPY ... TO PROGRAM, reading the server's files). Outside dev, "
    "Query runs only as a login that is not one."
)
DENIED = {"42501"}  # insufficient privilege: a secret's column, asked for
ON_ROWS = "read the table's Rows, where secrets are hidden"
_readers: dict[str, str | None] = {}  # by database: its reader, if set up


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
    reader = reader_role(engine or db_rows.app_engine(), hidden, metadata)
    started = time.monotonic()
    try:
        with db_rows.reading(engine, metadata) as conn:
            postgres = conn.dialect.name != "sqlite"
            try:
                if postgres:
                    _vet(conn, one, hidden, reader=reader)
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
        raise QueryError(_failed(exc, reader)) from None
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


def attempt(sql: str) -> tuple[str, Answer | str]:
    """``sql`` run (``run``) and how it went, for the audit: ``ran`` with its
    answer, else ``refused`` or ``stopped`` with why. Rows hidden here
    (``RowsHiddenError``) is no attempt, and raises."""
    try:
        return "ran", run(sql)
    except QueryError as exc:
        return "refused", str(exc)
    except db_rows.ReadTooSlowError as exc:
        return "stopped", str(exc)


def _vet(
    conn: Connection,
    one: str,
    hidden: Mapping[str, frozenset[str]],
    *,
    reader: str | None,
) -> None:
    """On Postgres, run as the ``reader`` role where it is set up; refuse a
    statement whose plan uses what it cannot show into (``unseen``) and,
    without the reader, a superuser outside dev and a plan reading a table
    holding a secret. Planning runs nothing."""
    if reader:
        role = conn.dialect.identifier_preparer.quote(reader)
        conn.exec_driver_sql(f"SET LOCAL ROLE {role}")
    elif (
        conn.exec_driver_sql("SELECT current_setting('is_superuser')").scalar() == "on"
        and not settings.is_dev
    ):
        raise QueryError(SUPERUSER)
    found = conn.exec_driver_sql(f"EXPLAIN (VERBOSE, FORMAT JSON) {one}").scalar()
    plan = json.loads(found) if isinstance(found, str) else found
    if name := unseen(plan):
        raise QueryError(
            f"It uses {name}, which reads or does what the plan cannot show, "
            "so a secret could pass unseen."
        )
    if not reader and (name := secret_read(plan, hidden)):
        raise QueryError(
            f"{name} holds a secret, which Postgres cannot blank in an answer: "
            f"{ON_ROWS}."
        )


def _code(exc: DBAPIError) -> str | None:
    """The SQLSTATE the driver gives (psycopg's ``sqlstate``, psycopg2's
    ``pgcode``)."""
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


def _failed(exc: DBAPIError, reader: str | None) -> str:
    """Why the database would not run it; a refusal of the ``reader``'s says
    what it may not do, and where to read the rest."""
    if reader and _code(exc) in DENIED:
        return (
            f"{exc.orig}. Query reads as a role that sees no column holding a "
            "secret and does nothing only a superuser may: name the other "
            f"columns, or {ON_ROWS}."
        )
    return str(exc.orig)


def reader_role(
    engine: Engine,
    hidden: Mapping[str, frozenset[str]],
    metadata: MetaData | None = None,
) -> str | None:
    """The reader role on ``engine``'s Postgres (``grants``), set up the first
    time a process asks; None on SQLite, or where the login may not make it
    (logged, the refusals stay, and it is not asked again). A failure that
    passes (a dropped connection) is asked again the next time."""
    if engine.dialect.name != "postgresql":
        return None
    key = str(engine.url)
    if key not in _readers:
        try:
            _readers[key] = _make_reader(engine, hidden, metadata)
        except DBAPIError as exc:
            logger.warning(f"Query runs without a reader role: {exc.orig}")
            if _code(exc) not in DENIED:
                return None
            _readers[key] = None
    return _readers[key]


def _make_reader(
    engine: Engine, hidden: Mapping[str, frozenset[str]], metadata: MetaData | None
) -> str:
    """The login's reader (``<login>_overseer_reader``: roles span the
    server, and only the login that made one may hand it to itself), its
    grants made again on the tables the database has."""
    with engine.begin() as conn:
        login = conn.exec_driver_sql("SELECT current_user").scalar() or ""
        role = f"{login[:40]}_overseer_reader"
        schema = conn.exec_driver_sql("SELECT current_schema()").scalar() or ""
        rows = conn.exec_driver_sql("SELECT schemaname, tablename FROM pg_tables")
        present = {(s, t) for s, t in rows}
        tables = [
            t
            for t in db_rows.by_name(metadata).values()
            if (t.schema or schema, t.name) in present
        ]
        quote = conn.dialect.identifier_preparer.quote
        for line in grants(role, tables, hidden, schema, quote):
            conn.exec_driver_sql(line)
    return role


def grants(
    reader: str,
    tables: Sequence[Table],
    hidden: Mapping[str, frozenset[str]],
    schema: str,
    quote: Callable[[str], str],
) -> list[str]:
    """What lets ``reader`` read the tables in the models' schemas
    (``schema`` where a table names none), each model table only the columns
    the models know but a secret's (column privileges): a column a later
    migration adds stays unread until the grants are made again, as each
    process starts. One process at a time (an advisory lock), so two never
    make the role or its grants at once."""
    role = quote(reader)
    found = [
        f"SELECT pg_advisory_xact_lock(hashtext('{reader}'))",
        f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        f"GRANT {role} TO CURRENT_USER",
    ]
    for each in sorted({t.schema or schema for t in tables} | {schema}):
        found += [
            f"GRANT USAGE ON SCHEMA {quote(each)} TO {role}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {quote(each)} TO {role}",
        ]
    for table in tables:
        secret = hidden.get(table.name, frozenset())
        name = f"{quote(table.schema or schema)}.{quote(table.name)}"
        shown = [quote(c.name) for c in table.columns if c.name not in secret]
        found.append(f"REVOKE SELECT ON {name} FROM {role}")
        if shown:
            found.append(f"GRANT SELECT ({', '.join(shown)}) ON {name} TO {role}")
    return found


def secret_read(plan: Any, hidden: Mapping[str, frozenset[str]]) -> str | None:
    """The first table holding a secret that ``plan`` (``EXPLAIN (FORMAT
    JSON)``) reads, or None."""
    return next((name for name in _relations(plan) if name in hidden), None)


def unseen(plan: Any) -> str | None:
    """The first of ``UNSEEN`` that ``plan`` (``EXPLAIN (VERBOSE, FORMAT
    JSON)``: every call and table it names) names, or None."""
    found = (UNSEEN.search(text) for text in _texts(plan))
    return next((m[1] for m in found if m), None)


def _texts(plan: Any) -> Iterator[str]:
    """Every text a plan holds, however deep."""
    if isinstance(plan, str):
        yield plan
    elif isinstance(plan, dict | list):
        for value in plan.values() if isinstance(plan, dict) else plan:
            yield from _texts(value)


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
