"""Every session the app opens for itself lands in the app-owned test database.

``_no_production_database`` redirects the module-level session factories in
``app.core.db`` so startup hooks, background tasks and service code that open
their own session never touch the database in ``DATABASE_URL``. The sync
factory must be covered as well as the async one: ``db_session()`` is what
startup hooks and the scheduler still use, and on a Postgres project nothing
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


def test_a_developer_env_never_points_the_suite_at_a_real_database(
    tmp_path,
) -> None:
    """Every ``DATABASE_URL_*`` setting the app or alembic prefers over
    ``DATABASE_URL`` is blanked in conftest, so a ``.env`` naming a real
    database never wins. A new one fails here until conftest blanks it."""
    from app.core.config import Settings

    redirects = [
        name for name in Settings.model_fields if name.startswith("DATABASE_URL_")
    ]
    if not redirects:
        pytest.skip("a SQLite stack has no setting that redirects the database")
    env = tmp_path / ".env"
    env.write_text(
        "".join(f"{name}=postgresql://dev@localhost:5432/live\n" for name in redirects)
    )
    settings = Settings(_env_file=env)
    urls = {
        settings.database_url_effective,
        getattr(settings, "migration_database_url", settings.database_url_effective),
    }
    assert all(url.startswith("sqlite:///") for url in urls), urls
