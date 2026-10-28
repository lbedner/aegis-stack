"""A Postgres project's revisions replayed on scratch SQLite.

``migrate_gen`` falls back to SQLite when no Postgres answers (an update
run with the stack down), each Postgres schema an attached database.
SQLite holds no foreign key across attached databases, so a revision that
adds one from a table in a schema to ``user`` replays as SQLite makes of
it, nothing; and a key an existing revision adds is not written again.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# A stack without a database has neither alembic nor SQLAlchemy; alembic is
# imported in the tests (a stack without it would sort it apart).
pytest.importorskip("alembic", reason="no database component in this stack")

from sqlalchemy import Connection, create_engine, event  # noqa: E402
from sqlalchemy.exc import NoReferencedTableError  # noqa: E402


@pytest.fixture
def attached(tmp_path: Path) -> Iterator[Connection]:
    """SQLite with a ``finance`` schema attached, ``user`` in the main one."""
    engine = create_engine(f"sqlite:///{tmp_path / 'scratch.sqlite'}")

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn: Any, _record: object) -> None:
        dbapi_conn.execute(
            f"ATTACH DATABASE '{tmp_path / 'finance.sqlite'}' AS finance"
        )

    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE "user" (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql(
            "CREATE TABLE finance.finance_account "
            "(id INTEGER PRIMARY KEY, owner_user_id INTEGER)"
        )
        yield conn


def _key_to_user(conn: Connection) -> None:
    """What a finance auth link revision does, as ``migrate_gen`` writes it."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import app.cli.migrate_sqlite  # noqa: F401 - what migrate_gen replays with

    with Operations(MigrationContext.configure(conn)).batch_alter_table(
        "finance_account", schema="finance"
    ) as batch_op:
        batch_op.create_foreign_key(
            "fk_finance_account_owner_user_id", "user", ["owner_user_id"], ["id"]
        )


def test_a_scratch_replay_adds_the_key_as_sqlite_would_none(
    attached: Connection,
) -> None:
    from app.cli.plugin_data import SCRATCH

    attached.info[SCRATCH] = True
    _key_to_user(attached)


def test_outside_a_scratch_replay_nothing_is_skipped(attached: Connection) -> None:
    """Only ``migrate_gen``'s own scratch database is spared the key."""
    with pytest.raises(NoReferencedTableError):
        _key_to_user(attached)


def _key(name: str, referent_schema: str | None = None) -> Any:
    from alembic.operations import ops

    return ops.CreateForeignKeyOp(
        name, "finance_account", "user", ["owner_user_id"], ["id"],
        source_schema="finance", referent_schema=referent_schema,
    )  # fmt: skip


def test_a_key_a_revision_already_adds_is_not_written_again(tmp_path: Path) -> None:
    from app.cli.migrate_sqlite import kept_by_a_revision

    (tmp_path / "003_finance_auth_link.py").write_text(
        'batch_op.create_foreign_key("fk_finance_account_owner_user_id", "user")'
    )
    assert kept_by_a_revision(_key("fk_finance_account_owner_user_id"), tmp_path)
    assert not kept_by_a_revision(_key("fk_finance_budget_owner_user_id"), tmp_path)


def test_a_key_within_one_schema_is_compared_as_ever(tmp_path: Path) -> None:
    """SQLite reflects a key inside one database, so it is not this case."""
    from app.cli.migrate_sqlite import kept_by_a_revision

    (tmp_path / "003_x.py").write_text('"fk_inside"')
    assert not kept_by_a_revision(
        _key("fk_inside", referent_schema="finance"), tmp_path
    )
