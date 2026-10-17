"""The database: the one SQL store (SQLite or PostgreSQL) every part keeps
its tables in, opened through ``app.core.db``'s engine and sessions and
migrated by Alembic.

This package holds only the component's own tables: what Overseer's Query
keeps (``saved``)."""

# Its tables no model declares, each with what it holds (``ontology``).
TABLES = {"alembic_version": "Which migration the database is at, kept by Alembic"}
