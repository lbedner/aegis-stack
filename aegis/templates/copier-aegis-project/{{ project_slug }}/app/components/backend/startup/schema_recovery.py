"""Schema-level recovery helpers for startup database init.

``_existing_tables_by_schema`` reads what actually exists (schema-qualified
to match ``SQLModel.metadata``); ``_create_missing_tables`` is the safety
net that recreates any model table a stamp marked applied without running -
so a stamp-based recovery can never leave the schema stamped-but-incomplete.
"""

from __future__ import annotations

from typing import Any

from app.core.log import logger


def _existing_tables_by_schema(inspector: Any) -> set[str]:
    """Existing tables across every schema our models use, keyed to match
    ``SQLModel.metadata.tables``: schema-qualified (``schema.name``) for
    non-default schemas, bare otherwise. Without the qualification a table
    in a component schema (e.g. ``scheduler``) reads as missing.
    """
    from sqlmodel import SQLModel

    model_schemas = {table.schema for table in SQLModel.metadata.tables.values()}
    existing: set[str] = set()
    for schema in model_schemas:
        for name in inspector.get_table_names(schema=schema):
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
        logger.debug(f"Missing-table backfill skipped: {e}")
