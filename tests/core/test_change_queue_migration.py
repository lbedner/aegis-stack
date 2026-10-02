"""The propose/approve queue's table, out of finance and into its own revision.

``pending_change`` ships with any stack that can propose (finance, or AI
on a persistent backend). A project that had the queue as
``finance_pending_change`` keeps its rows, ids included: chat transcripts
point at them by id.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from aegis.core.migration_generator import (
    CHANGE_QUEUE_MIGRATION,
    MIGRATION_SPECS,
    _place_data_statements,
    get_services_needing_migrations,
)

_COLUMNS = (
    "id INTEGER PRIMARY KEY, owner_user_id INTEGER, "
    "change_type VARCHAR(64) NOT NULL, payload JSON NOT NULL, "
    "proposed_by_agent VARCHAR(64), conversation_id VARCHAR(64), "
    "batch_id VARCHAR(36), status VARCHAR(16) NOT NULL, result JSON NOT NULL, "
    "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
    "resolved_at DATETIME"
)


def _needs(**context: object) -> list[str]:
    return get_services_needing_migrations(context)


def test_finance_alone_ships_the_queue_after_its_own_tables() -> None:
    services = _needs(include_finance=True, include_auth=True)
    assert services.index("auth") < services.index("change_queue")
    assert services.index("finance_auth_link") < services.index("change_queue")


def test_ai_on_a_persistent_backend_ships_the_queue_without_finance() -> None:
    assert "change_queue" in _needs(include_ai=True, ai_backend="sqlite")


def test_no_proposer_no_queue() -> None:
    assert "change_queue" not in _needs(include_ai=True, ai_backend="memory")
    assert "change_queue" not in _needs(include_auth=True)


def test_the_spec_is_registered() -> None:
    assert MIGRATION_SPECS["change_queue"] is CHANGE_QUEUE_MIGRATION


def test_the_carry_over_runs_after_the_table_exists(tmp_path: Path) -> None:
    revision = tmp_path / "021_change_queue.py"
    revision.write_text(
        '"""change_queue"""\n'
        "def upgrade() -> None:\n"
        '    op.create_table("pending_change")\n'
        "\n\ndef downgrade() -> None:\n    pass\n"
    )

    _place_data_statements(tmp_path, ["change_queue"], [revision])

    src = revision.read_text()
    upgrade = src.partition("def downgrade")[0]
    assert upgrade.index("create_table") < upgrade.index("finance_pending_change")


def _upgrade(conn: sa.Connection) -> None:
    body = CHANGE_QUEUE_MIGRATION.data_after
    namespace: dict[str, object] = {
        "op": Operations(MigrationContext.configure(conn)),
        "sa": sa,
    }
    exec(compile(f"def upgrade():\n{body}\n", "revision", "exec"), namespace)
    namespace["upgrade"]()  # type: ignore[operator]


def test_finance_rows_move_with_their_ids() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE TABLE finance_pending_change ({_COLUMNS})")
        conn.exec_driver_sql(f"CREATE TABLE pending_change ({_COLUMNS})")
        conn.exec_driver_sql(
            "INSERT INTO finance_pending_change (id, change_type, payload, status,"
            " result, created_at, updated_at) VALUES (7, 'transaction.categorize',"
            " '{}', 'approved', '{}', '2026-09-01', '2026-09-01')"
        )

        _upgrade(conn)

        rows = conn.exec_driver_sql(
            "SELECT id, change_type, status FROM pending_change"
        ).all()
        assert rows == [(7, "transaction.categorize", "approved")]
        assert not sa.inspect(conn).has_table("finance_pending_change")


def test_a_project_that_never_had_the_old_table_is_untouched() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE TABLE pending_change ({_COLUMNS})")

        _upgrade(conn)

        assert conn.exec_driver_sql("SELECT COUNT(*) FROM pending_change").scalar() == 0
