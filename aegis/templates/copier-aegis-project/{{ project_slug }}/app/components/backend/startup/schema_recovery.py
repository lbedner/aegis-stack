"""Schema-level recovery helpers for startup database init.

``_existing_tables_by_schema`` reads what actually exists (schema-qualified
to match ``SQLModel.metadata``); ``_reflect_schema`` gathers the columns and
keys a stamp decision needs, while the connection is still open;
``_signature_satisfied`` decides one revision against those facts; and
``_create_missing_tables`` is the safety net that recreates any model table a
stamp marked applied without running - so a stamp-based recovery can never
leave the schema stamped-but-incomplete.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from app.core.log import logger


def _existing_tables_by_schema(inspector: Any) -> set[str]:
    """Existing tables across every schema our models use, keyed to match
    ``SQLModel.metadata.tables``: schema-qualified (``schema.name``) for
    non-default schemas, bare otherwise. Without the qualification a table
    in a component schema (e.g. ``scheduler``) reads as missing.
    """
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import SQLModel

    model_schemas = {table.schema for table in SQLModel.metadata.tables.values()}
    existing: set[str] = set()
    for schema in model_schemas:
        try:
            names = inspector.get_table_names(schema=schema)
        except SQLAlchemyError as exc:
            # A schema the models declare but this database has not created
            # yet holds no tables - that is an answer, not a failure. Letting
            # it raise aborted the caller's whole pass, and the caller
            # swallows, so the recovery silently stopped running.
            logger.debug(f"Schema {schema!r} not present yet: {exc}")
            continue
        for name in names:
            existing.add(f"{schema}.{name}" if schema else name)
    return existing


def _create_missing_tables() -> None:
    """Create any model table still missing after migrations.

    A safety net for the stale-revision / stamp recovery: stamping the DB to
    head can mark a migration "applied" without running it, leaving a table
    it should have created absent (e.g. a new component table against a
    persisted volume from a different project lineage). This recreates only
    the missing tables (and their schema) directly from the model metadata,
    so the schema can never be left stamped-but-incomplete. Idempotent.
    """
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlmodel import SQLModel, text

        from app.core.db import engine

        existing = _existing_tables_by_schema(sa_inspect(engine))
        missing = [
            table
            for key, table in SQLModel.metadata.tables.items()
            if key not in existing and key != "alembic_version"
        ]
        if not missing:
            return

        # create_all does not create schemas; ensure non-default ones exist.
        schemas = {table.schema for table in missing if table.schema}
        with engine.begin() as conn:
            for schema in schemas:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

        SQLModel.metadata.create_all(engine, tables=missing)
        logger.warning(
            "Created missing table(s) after migrations: "
            f"{sorted(table.name for table in missing)}"
        )
    except Exception as e:
        logger.warning(f"Missing-table backfill skipped: {e}")


def _row_exists(conn: Any, table: str, where: str) -> bool:
    """Whether ``SELECT 1 FROM table WHERE where`` finds a row.

    The ``("row", table, where)`` signature form: proof for a data-only
    revision (``finance_auth_link`` inserts user 0). A table, column or FK
    cannot prove such a revision ran - the FK it used to add is inline in
    the ``finance`` revision now - and stamping it on a persisted volume
    would skip the only INSERT that satisfies that FK (aegis-stack#1110).
    """
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import text

    schema, _, bare = table.rpartition(".")
    qualified = f'"{schema}"."{bare}"' if schema else f'"{bare}"'
    try:
        result = conn.execute(text(f"SELECT 1 FROM {qualified} WHERE {where} LIMIT 1"))
    except SQLAlchemyError:
        # No such table (or no such column) means the revision has not run.
        return False
    return result.first() is not None


class _SchemaFacts(NamedTuple):
    """What the database already has, read while the connection is open."""

    tables: set[str]
    columns: dict[str, set[str]]
    foreign_keys: dict[str, set[str]]


def _reflect_schema(connection: Any) -> _SchemaFacts:
    """Gather every fact the stamp pass needs, before the session closes.

    An inspector that outlives its connection raises on every call, and the
    caller swallowed those raises - so the column map was always empty and
    only ``("table", ...)`` signatures could ever match. Column and
    foreign-key ones silently never stamped, and a version pointer left
    below the last table-signed revision replayed DDL on every boot
    (aegis-stack#1123).

    Each table is recorded under both its qualified and bare spelling:
    signatures use the qualified form, and SQLite has no schemas.
    """
    from sqlalchemy import inspect
    from sqlalchemy.exc import SQLAlchemyError

    inspector = inspect(connection)
    tables = _existing_tables_by_schema(inspector)
    columns: dict[str, set[str]] = {}
    foreign_keys: dict[str, set[str]] = {}
    for table in tables:
        schema, _, bare = table.rpartition(".")
        try:
            reflected = {
                column["name"]
                for column in inspector.get_columns(bare, schema=schema or None)
            }
            keys = {
                constrained
                for fk in inspector.get_foreign_keys(bare, schema=schema or None)
                for constrained in fk.get("constrained_columns", ())
            }
        except SQLAlchemyError as exc:
            # Listed but not reflectable. Its signature stays unproven and
            # the revision replays, which is the safe outcome - but say so,
            # because silence here is what hid this bug.
            logger.warning(f"Could not reflect {table} for stamping: {exc}")
            continue
        for name in (table, bare):
            columns[name] = reflected
            foreign_keys[name] = keys
    return _SchemaFacts(tables=tables, columns=columns, foreign_keys=foreign_keys)


def _by_either_spelling(facts: dict[str, set[str]], table: str) -> set[str]:
    """Qualified name first, bare second - ``_reflect_schema`` records both."""
    return facts.get(table) or facts.get(table.split(".")[-1], set())


def _signature_satisfied(
    sig: tuple[str, ...], facts: _SchemaFacts, connection: Any
) -> bool:
    """Whether the schema already carries what this revision would add."""
    kind = sig[0]
    if kind == "table":
        return sig[1] in facts.tables or sig[1].split(".")[-1] in facts.tables
    if kind == "column":
        return sig[2] in _by_either_spelling(facts.columns, sig[1])
    if kind == "foreign_key":
        return sig[2] in _by_either_spelling(facts.foreign_keys, sig[1])
    if kind == "row":
        return _row_exists(connection, sig[1], sig[2])
    logger.warning(f"Unknown stamp signature form {kind!r}; treating as unproven")
    return False


def _revisions_oldest_first(script: Any) -> list[Any]:
    """``walk_revisions`` yields newest-first, and stamping is a pointer move.

    Walking newest-first left the version pointer at the OLDEST matched
    revision, undoing every stamp before it (aegis-stack#1123).
    """
    return list(reversed(list(script.walk_revisions())))


def _adoptable(
    chain: list[str], current: str | None, proven: Callable[[str], bool]
) -> list[str]:
    """Pending revisions, oldest first, whose objects already exist - up to
    the first that cannot prove it.

    ``chain`` is the revision ids oldest-first, and position in it is the
    order: ids are never compared as strings, which breaks on hash ids or
    past the zero padding. Stopping at the first unproven revision is the
    point. Stamping a later one past it moved the version over DDL that
    never ran - APScheduler builds the scheduler's table on first boot, so
    its revision proved itself ahead of an AI revision that had not run.
    """
    if current is None:
        start = 0
    elif current in chain:
        start = chain.index(current) + 1
    else:
        # Unknown to this chain: the stale-revision pass owns that case.
        return []
    adopted: list[str] = []
    for revision in chain[start:]:
        if not proven(revision):
            break
        adopted.append(revision)
    return adopted
