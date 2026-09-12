"""Every session the app opens for itself lands in the app-owned test database.

``_no_production_database`` redirects the module-level session factories in
``app.core.db`` so startup hooks, background tasks and service code that open
their own session never touch the database in ``DATABASE_URL``. The sync
factory must be covered as well as the async one: ``db_session()`` is what
``get_conversation()`` and friends use, and on a Postgres project nothing
else creates tables for it (startup migrations begin with ``CREATE SCHEMA``,
which SQLite rejects), so an uncovered sync path fails with "no such table"
on the first lookup a route makes after a write.
"""

from __future__ import annotations

import pytest

# Skip before touching SQLAlchemy: a stack without a database ships neither.
db_module = pytest.importorskip("app.core.db", reason="no database in this stack")

from sqlalchemy import inspect  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402


def test_sync_and_async_app_owned_sessions_share_one_database(
    app_owned_engine,
) -> None:
    with db_module.db_session(autocommit=False) as session:
        bind = session.get_bind()
        assert bind.url.database == app_owned_engine.url.database
        present = set(inspect(bind).get_table_names())
    expected = {t.name for t in SQLModel.metadata.tables.values() if t.schema is None}
    assert expected <= present, sorted(expected - present)
