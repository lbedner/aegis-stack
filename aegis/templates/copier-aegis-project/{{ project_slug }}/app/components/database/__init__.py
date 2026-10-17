"""The database component's own tables: what Overseer's Query keeps
(``saved``). The engine, sessions and migrations are ``app.core.db``'s."""

# Its tables no model declares, each with what it holds (``ontology``).
TABLES = {"alembic_version": "Which migration the database is at, kept by Alembic"}
