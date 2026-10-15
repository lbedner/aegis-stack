"""A table's rows, a page at a time, as Overseer reads them (Database >
Tables > Rows), shown only where ``exposure.shown`` allows. Only a table
the app's models declare (``table_of``: a name is looked up, never put
into SQL); sorted only by an indexed column, filtered by the columns
``filterable`` names; never by a column holding a secret. Each foreign
key (``keys``), out of a table and into it, leads from a row to
the rows it points at or that point at it (``follow``): a table and the
filter that finds them.

The default order, by the table's key, pages from where the last page
ended (``next``/``prev``), so a deep page costs what the first does;
another order pages by offset, at most ``MAX_DEPTH`` pages in. A secret
never leaves the database (its column is selected as ``HIDDEN``); text is
read to ``READ`` characters, redacted, then cut. A read stops past
``SECONDS``. It goes through the app's sync session factory, which never
begins a write transaction (on SQLite the async engine starts each with
``BEGIN IMMEDIATE`` and would hold the write lock for as long as it ran),
on a connection that only reads (``reading``, which ``db_query`` shares)."""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
import sqlite3
import time
from typing import Any

from sqlalchemy import (
    Column,
    Connection,
    Engine,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.exc import DBAPIError
from sqlmodel import SQLModel

from app.core import exposure
from app.services.system import db_filters
from app.services.system.errors import redact

PAGE = 25  # rows a page shows
MAX_DEPTH = 400  # the deepest page by offset (10k rows in)
CELL = 120  # characters a cell shows before it is cut
READ = 1024  # characters text is read to: room to find a password to hide
SECONDS = 5.0  # the longest a read may run
STEPS = 1000  # SQLite instructions between looks at the clock
HIDDEN = "••••••"
# What a statement may not do on SQLite, whose query_only it could undo.
REFUSED = frozenset(
    {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}
)


class RowsHiddenError(Exception):
    """The rows are not shown here (``exposure.shown``)."""


class ReadTooSlowError(Exception):
    """A read ran past ``SECONDS`` and was stopped."""


class RowsUnreadError(Exception):
    """The database could not read the table (not migrated yet, say)."""


@dataclass(frozen=True)
class Key:
    """A foreign key, whole: ``columns`` of ``table`` pointing at ``to``
    of ``target``, as the models declare it."""

    table: str
    columns: tuple[str, ...]
    target: str
    to: tuple[str, ...]
    optional: bool = False  # a key column may be empty: a row need point nowhere
    one: bool = False  # its columns are unique: one row at most points at each
    ondelete: str = "NO ACTION"  # what deleting the row pointed at does


@dataclass(frozen=True)
class Rows:
    """A page of a table: its columns, its rows as text, and the query
    changes that reach the pages either side."""

    columns: list[str]
    rows: list[list[str]]
    masked: frozenset[str]
    key: str | None  # the single-column key keyset paging runs on
    sortable: list[str]  # the columns it may be ordered by
    next: dict[str, str] | None = None
    prev: dict[str, str] | None = None


@cache
def models() -> MetaData:
    """Every model's table, each imported once (``import_all_models``):
    what is a secret is read from them, so it cannot hang on what this
    process happened to import."""
    from app.core.model_registry import import_all_models

    import_all_models()
    return SQLModel.metadata


def by_name(metadata: MetaData | None = None) -> dict[str, Table]:
    """The models' tables by bare name, as the health check and the
    ontology name them (never ``schema.name``)."""
    return {t.name: t for t in (metadata or models()).tables.values()}


def table_of(name: str, metadata: MetaData | None = None) -> Table | None:
    """The table the app's models declare under ``name``, or None."""
    return by_name(metadata).get(name)


def tables(present: Iterable[str] | None = None) -> list[str]:
    """The tables to offer: the models', only those the database has where
    the health check lists them (``present``), so none was never migrated."""
    names = set(by_name())
    return sorted(names & set(present) if present is not None else names)


@cache
def masked(table: Table) -> frozenset[str]:
    """The columns shown as hidden: one its model marks secret
    (``info={"secret": True}`` on its column, any type), and text or bytes
    named as one (``redact.secret_name``, as errors and logs are redacted)."""
    return frozenset(
        c.name
        for c in table.columns
        if c.info.get("secret")
        or (
            (db_filters.textual(c) or db_filters.holds(c) is bytes)
            and redact.secret_name(c.name)
        )
    )


def secrets(metadata: MetaData | None = None) -> dict[str, frozenset[str]]:
    """Each table holding a secret, by name, and the columns that do."""
    found = {name: masked(t) for name, t in by_name(metadata).items()}
    return {name: columns for name, columns in found.items() if columns}


def sortable(table: Table) -> list[str]:
    """The columns an index serves (the key, an indexed or unique column,
    an index's leading column), a secret's aside."""
    indexed = {c.name for c in table.primary_key.columns}
    indexed |= {c.name for c in table.columns if c.index or c.unique}
    indexed |= {next(iter(i.columns)).name for i in table.indexes if i.columns}
    indexed |= {
        next(iter(c.columns)).name
        for c in table.constraints
        if isinstance(c, UniqueConstraint) and c.columns
    }
    hidden = masked(table)
    return [c.name for c in table.columns if c.name in indexed - hidden]


def filterable(table: Table) -> list[str]:
    """What a filter may compare (``db_filters.filterable``), its secrets
    never."""
    return db_filters.filterable(table, masked(table))


def _unique(table: Table) -> set[frozenset[str]]:
    """Each set of columns no two rows share: the key, a unique column, a
    unique constraint or index."""
    found = {frozenset(c.name for c in table.primary_key.columns)}
    found |= {frozenset([c.name]) for c in table.columns if c.unique}
    found |= {
        frozenset(c.name for c in u.columns)
        for u in [*table.constraints, *table.indexes]
        if isinstance(u, UniqueConstraint) or getattr(u, "unique", False)
    }
    return found


def keys(table: Table) -> tuple[list[Key], list[Key]]:
    """``table``'s foreign keys out, and the keys of every table pointing
    into it, each by its table and columns."""
    found = [
        Key(
            c.table.name,
            tuple(e.parent.name for e in c.elements),
            c.referred_table.name,
            tuple(e.column.name for e in c.elements),
            optional=any(e.parent.nullable for e in c.elements),
            one=frozenset(e.parent.name for e in c.elements) in _unique(t),
            ondelete=(c.ondelete or "NO ACTION").upper(),
        )
        for t in by_name(table.metadata).values()
        for c in t.foreign_key_constraints
        if t is table or c.referred_table is table
    ]
    found.sort(key=lambda k: (k.table, k.columns))
    return [k for k in found if k.table == table.name], [
        k for k in found if k.target == table.name
    ]


def follow(
    key: Key,
    row: Mapping[str, str],
    *,
    out: bool,
    metadata: MetaData | None = None,
) -> tuple[str, str] | None:
    """Where ``key`` leads from ``row`` (its cells by column): out, to the
    row it points at; in, to the rows pointing at it. The table and the
    filter (``parse_where``) that finds them; None where a value is empty,
    hidden, cut or holds a comma, or the other table may not be filtered
    by those columns."""
    mine, theirs, table = (
        (key.columns, key.to, key.target) if out else (key.to, key.columns, key.table)
    )
    values = [row.get(c, "") for c in mine]
    if any(not v or v == HIDDEN or v.endswith("…") or "," in v for v in values):
        return None
    other = table_of(table, metadata)
    if other is None or not set(theirs) <= set(filterable(other)):
        return None
    return table, db_filters.where_text(
        [(c, ":", v) for c, v in zip(theirs, values, strict=True)]
    )


def _key(table: Table) -> Column[Any] | None:
    """The single-column key pages run on; none when it holds a secret or
    text (paging from it would order text, and carry its values whole in
    the page links, past what the cells redact)."""
    keys = list(table.primary_key.columns)
    one = keys[0] if len(keys) == 1 else None
    if one is None or one.name in masked(table) or db_filters.textual(one):
        return None
    return one


def _selected(table: Table, key: Column[Any] | None) -> list[Any]:
    """Each column as the page reads it: a secret as ``HIDDEN``, binary as
    its length, text to ``READ`` characters, the rest (the key) whole."""
    hidden = masked(table)
    picked: list[Any] = []
    for c in table.columns:
        if c.name in hidden:
            picked.append(literal(HIDDEN, String).label(c.name))
        elif c is key:
            picked.append(c)
        elif db_filters.holds(c) is bytes:
            picked.append(func.length(c).label(c.name))
        elif db_filters.textual(c):
            picked.append(func.substr(cast(c, Text), 1, READ).label(c.name))
        else:
            picked.append(c)
    return picked


def page(
    table: Table,
    *,
    order: str | None = None,
    desc: bool = False,
    where: Sequence[db_filters.Filter] = (),
    after: str | None = None,
    before: str | None = None,
    number: int = 1,
    engine: Engine | None = None,
) -> Rows:
    """A page of ``table``'s rows: by its key from ``after`` (or back from
    ``before``) when ordered by it, else page ``number`` of ``order``;
    ``where`` keeps rows each filter's comparison holds for. Raises
    RowsHiddenError where rows are not shown, AskError for what cannot be
    asked, ReadTooSlowError past ``SECONDS``, RowsUnreadError where the
    database cannot read it."""
    require_shown()
    key = _key(table)
    sorts = sortable(table)
    if order is not None and order not in sorts:
        raise db_filters.AskError(f"{table.name} cannot be ordered by {order!r}")
    by = table.columns[order] if order else key
    query = select(*_selected(table, key))
    if where:
        query = query.where(*db_filters.conditions(table, where, filterable(table)))
    binary = {c.name for c in table.columns if db_filters.holds(c) is bytes}
    names = table.columns.keys()
    if key is not None and by is key:
        back = after is None and before is not None
        cursor = before if back else after
        descending = desc != back  # back from a page reads the other way
        if cursor is not None:
            value = db_filters.value(key, cursor)
            query = query.where(key < value if descending else key > value)
        query = query.order_by(key.desc() if descending else key.asc())
        found = _read(engine, table, query.limit(PAGE + 1))
        more, found = len(found) > PAGE, found[:PAGE]
        if back:
            found.reverse()
        at = names.index(key.name)
        first, last = (str(found[0][at]), str(found[-1][at])) if found else ("", "")
        newer, older = (True, more) if back else (more, cursor is not None)
        nxt = {"after": last} if newer and found else None
        prev = {"before": first} if older and found else None
    else:
        if not 1 <= number <= MAX_DEPTH:
            raise db_filters.AskError(f"Pages by offset go {MAX_DEPTH} deep at most")
        # Ties broken by the key, or the database may order them differently
        # each page (PostgreSQL does), repeating rows and losing others.
        keyed = list(table.primary_key.columns)
        ordering = [by, *(c for c in keyed if c is not by)] if by is not None else keyed
        query = query.order_by(*(c.desc() if desc else c.asc() for c in ordering))
        found = _read(engine, table, query.offset((number - 1) * PAGE).limit(PAGE + 1))
        more, found = len(found) > PAGE, found[:PAGE]
        nxt = {"page": str(number + 1)} if more else None
        prev = {"page": str(number - 1)} if number > 1 else None
    return Rows(
        columns=list(names),
        rows=[
            [cell(v, n in binary) for n, v in zip(names, row, strict=True)]
            for row in found
        ],
        masked=masked(table),
        key=key.name if key is not None else None,
        sortable=sorts,
        next=nxt,
        prev=prev,
    )


def require_shown() -> None:
    """RowsHiddenError, saying why, where the app's rows are not shown."""
    if refused := exposure.refusal(exposure.ROWS):
        raise RowsHiddenError(f"A table's rows are the app's data: {refused}")


def app_engine() -> Engine:
    """The engine the app's sync sessions use (``SessionLocal``)."""
    from app.core import db

    return db.SessionLocal.kw["bind"]


@contextmanager
def reading(
    engine: Engine | None = None, metadata: MetaData | None = None
) -> Iterator[Connection]:
    """A connection that only reads, stopped past ``SECONDS``
    (ReadTooSlowError). Postgres: a read-only transaction. SQLite: no write
    lock is taken, ``query_only`` is on, an authorizer refuses ``ATTACH``,
    ``DETACH`` and every ``PRAGMA`` (so no statement can undo it) and reads
    every column ``metadata``'s models hold a secret in as empty, however a
    statement reaches it; all of it undone before the connection goes back."""
    deadline = time.monotonic() + SECONDS
    with (engine or app_engine()).connect() as conn:
        sqlite = conn.dialect.name == "sqlite"
        raw = conn.connection.driver_connection if sqlite else None
        if raw is not None:
            raw.execute("PRAGMA query_only = ON")
            raw.set_authorizer(_authorizer(secrets(metadata)))
            raw.set_progress_handler(lambda: int(time.monotonic() > deadline), STEPS)
        else:
            conn = conn.execution_options(postgresql_readonly=True)
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(SECONDS * 1000)}")
        try:
            yield conn
        except DBAPIError as exc:
            if "interrupt" in str(exc) or "statement timeout" in str(exc):
                raise ReadTooSlowError(f"Stopped after {SECONDS:g} s.") from None
            raise
        finally:
            if raw is not None:
                raw.set_progress_handler(None, 0)
                raw.set_authorizer(None)
                raw.execute("PRAGMA query_only = OFF")


def _authorizer(hidden: dict[str, frozenset[str]]) -> Callable[..., int]:
    """SQLite's say on each step of a statement (``reading``)."""

    def authorize(action: int, table: str | None, column: str | None, *_: Any) -> int:
        if action in REFUSED:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and column in hidden.get(table or "", ()):
            return sqlite3.SQLITE_IGNORE
        return sqlite3.SQLITE_OK

    return authorize


def _read(engine: Engine | None, table: Table, query: Any) -> list[Sequence[Any]]:
    """``query``'s rows of ``table`` (``reading``); RowsUnreadError where the
    database cannot read it."""
    try:
        with reading(engine, table.metadata) as conn:
            return [tuple(row) for row in conn.execute(query)]
    except DBAPIError as exc:
        raise RowsUnreadError(f"{table.name} could not be read: {exc.orig}") from None


def cell(value: Any, binary: bool) -> str:
    """A value as a cell shows it: binary (its length here) as its size,
    text redacted then cut at ``CELL``."""
    if value is None:
        return ""
    if binary:
        return f"binary, {value:,} bytes"
    text = redact.text(value) if isinstance(value, str) else str(value)
    return text if len(text) <= CELL else text[:CELL] + "…"
