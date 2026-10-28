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

import pytest
from sqlalchemy import Connection, create_engine, event
from sqlalchemy.exc import NoReferencedTableError

from alembic.migration import MigrationContext
from alembic.operations import Operations, ops

pytest.importorskip(
    "app.components.backend.startup.migration_signatures",
    reason="no database component in this stack",
)

from app.cli.migrate_sqlite import kept_by_a_revision  # noqa: E402
from app.cli.plugin_data import SCRATCH  # noqa: E402


@pytest.fixture
def attached(tmp_path: Path) -> Iterator[Connection]:
    """SQLite with a ``finance`` schema attached, ``user`` in the main one."""
    engine = create_engine(f"sqlite:///{tmp_path / 'scratch.sqlite'}")

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn: object, _record: object) -> None:
        dbapi_conn.execute(  # type: ignore[attr-defined]
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
    with Operations(MigrationContext.configure(conn)).batch_alter_table(
        "finance_account", schema="finance"
    ) as batch_op:
        batch_op.create_foreign_key(
            "fk_finance_account_owner_user_id", "user", ["owner_user_id"], ["id"]
        )


def test_a_scratch_replay_adds_the_key_as_sqlite_would_none(
    attached: Connection,
) -> None:
    attached.info[SCRATCH] = True
    _key_to_user(attached)


def test_outside_a_scratch_replay_nothing_is_skipped(attached: Connection) -> None:
    """Only ``migrate_gen``'s own scratch database is spared the key."""
    with pytest.raises(NoReferencedTableError):
        _key_to_user(attached)


def _key(name: str) -> ops.CreateForeignKeyOp:
    return ops.CreateForeignKeyOp(
        name, "finance_account", "user", ["owner_user_id"], ["id"],
        source_schema="finance",
    )  # fmt: skip


def test_a_key_a_revision_already_adds_is_not_written_again(tmp_path: Path) -> None:
    (tmp_path / "003_finance_auth_link.py").write_text(
        'batch_op.create_foreign_key("fk_finance_account_owner_user_id", "user")'
    )
    assert kept_by_a_revision(_key("fk_finance_account_owner_user_id"), tmp_path)
    assert not kept_by_a_revision(_key("fk_finance_budget_owner_user_id"), tmp_path)


def test_a_key_within_one_schema_is_compared_as_ever(tmp_path: Path) -> None:
    """SQLite reflects a key inside one database, so it is not this case."""
    (tmp_path / "003_x.py").write_text('"fk_inside"')
    inside = ops.CreateForeignKeyOp(
        "fk_inside", "finance_budget", "finance_account", ["account_id"], ["id"],
        source_schema="finance", referent_schema="finance",
    )  # fmt: skip
    assert not kept_by_a_revision(inside, tmp_path)
